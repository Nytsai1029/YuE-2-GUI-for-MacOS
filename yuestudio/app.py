"""FastAPI application: REST + SSE API and the built single-page UI."""
from __future__ import annotations

import io
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import __version__, service
from .abc import display
from .abc.score import try_parse
from .analysis import fit as F
from .analysis.plan import analyze
from .asr import ASR
from .db import DB
from .director.pipeline import Director
from .engine import Engine
from .engine.detect import detect
from .jobs.bus import Bus
from .jobs.lane import Lane
from .lyrics import syllables as S
from .lyrics.doc import parse as parse_lyrics
from .lyrics.normalize import SungOptions, sing_line
from .repair import apply_ops
from .rules import catalog
from .style import VOCAB

log = logging.getLogger("yuestudio")
STATIC = Path(__file__).parent / "static" / "app"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class CheckBody(BaseModel):
    lyrics: str = ""
    fields: dict = {}


class TakeBody(BaseModel):
    lyrics: str | None = None
    fields: dict | None = None
    draft_id: str | None = None
    preset: str = "standard"
    overrides: dict | None = None
    seed: int | None = None
    allow_errors: bool = False


class State:
    db: DB
    engine: Engine
    bus: Bus
    lane: Lane
    director: Director
    asr: ASR
    data_dir: Path
    host: str
    port: int


S_ = State()


def create_app(data_dir: Path, host: str = "127.0.0.1", port: int = 8765, fake: bool = False) -> FastAPI:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        S_.data_dir, S_.host, S_.port = data_dir, host, port
        S_.db = DB(data_dir / "studio.db")
        if fake:
            S_.db.save_settings({"engine": {"mode": "fake"}})
        S_.bus = Bus()
        S_.engine = Engine(data_dir, S_.db.settings)
        S_.engine.listeners.append(lambda e: S_.bus.publish("engine", **e))
        S_.asr = ASR(S_.db.settings)
        S_.director = Director(S_.db, S_.engine, S_.bus, data_dir, S_.db.settings, S_.asr)
        S_.lane = Lane(S_.db, S_.director, S_.engine, S_.bus)
        S_.lane.start()
        threading.Thread(target=_warmup, name="warmup", daemon=True).start()
        yield
        S_.lane.stop()
        S_.asr.release()
        S_.engine.shutdown()

    app = FastAPI(title="YuE Studio", version=__version__, lifespan=lifespan)

    # ------------------------------------------------------------------ security
    @app.middleware("http")
    async def guard(request: Request, call_next):
        settings = S_.db.settings() if hasattr(S_, "db") else {"server": {}}
        lan = bool(settings["server"].get("lan"))
        hostname = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        client = request.client.host if request.client else ""
        local_client = client in LOOPBACK or client == "testclient"
        if not lan and hostname not in LOOPBACK and hostname != "testserver":
            return JSONResponse({"detail": "Host not allowed"}, status_code=421)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin.split("://", 1)[-1].rsplit(":", 1)[0].strip("[]").lower() != hostname:
                return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
        path = request.url.path
        loopback_only = path.startswith(("/api/settings", "/api/engine/detect", "/api/diagnostics")) or \
            path == "/api/system/pick-folder"
        if loopback_only and not local_client:
            return JSONResponse({"detail": "Only available on this Mac"}, status_code=403)
        if lan and not local_client and path.startswith("/api"):
            token = settings["server"].get("token")
            if token and request.cookies.get("ys_token") != token and request.headers.get("x-studio-token") != token:
                return JSONResponse({"detail": "Access token required"}, status_code=401)
        return await call_next(request)

    # ------------------------------------------------------------------ system
    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/system")
    def system():
        return {"version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
                "machine": platform.machine(), "data_dir": str(S_.data_dir), "ffmpeg": bool(shutil.which("ffmpeg")),
                "asr": S_.asr.provider(), "engine": S_.engine.info(), "queue": S_.lane.queue(),
                "calibration": S_.db.settings()["calibration"]}

    @app.post("/api/system/pick-folder")
    def pick_folder(body: dict):
        prompt = str(body.get("prompt") or "Choose a folder").replace('"', "'")
        if platform.system() != "Darwin":
            raise HTTPException(501, "Native picker is only available on macOS; paste the path instead.")
        res = subprocess.run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{prompt}")'],
                             capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            return {"path": None}
        return {"path": res.stdout.strip().rstrip("/")}

    @app.get("/api/settings")
    def get_settings():
        return S_.db.settings()

    @app.put("/api/settings")
    def put_settings(body: dict):
        before = S_.db.settings()["engine"]
        merged = S_.db.save_settings(body)
        if merged["engine"] != before and S_.lane.current is None:
            S_.engine.shutdown()  # reload with the new profile on next use
        return merged

    @app.post("/api/engine/detect")
    def engine_detect(body: dict):
        return detect(body.get("mlx_yue_dir") or None)

    @app.get("/api/engine")
    def engine_info():
        return S_.engine.info()

    @app.post("/api/engine/load")
    def engine_load():
        job = S_.lane.submit("warmup", None, {})
        return {"job": job["id"]}

    @app.post("/api/engine/unload")
    def engine_unload():
        if S_.lane.current is not None:
            raise HTTPException(409, "A job is running")
        S_.engine.shutdown()
        return S_.engine.info()

    @app.get("/api/vocab")
    def vocab():
        return VOCAB

    @app.get("/api/rules")
    def rules():
        return catalog()

    # ------------------------------------------------------------------ writing
    @app.post("/api/check")
    def check(body: CheckBody):
        return service.check(body.lyrics, body.fields, S_.db.lexicon())

    @app.get("/api/lexicon")
    def lexicon():
        return S_.db.all("SELECT * FROM lexicon ORDER BY term")

    @app.post("/api/lexicon")
    def lexicon_add(body: dict):
        term, sung = str(body.get("term", "")).strip(), str(body.get("sung", "")).strip()
        if not term or not sung:
            raise HTTPException(400, "term and sung are required")
        S_.db.execute("INSERT INTO lexicon(term, sung, lang, created) VALUES(?,?,?,?) ON CONFLICT(term) DO UPDATE "
                      "SET sung=excluded.sung", (term, sung, body.get("lang"), time.time()))
        return {"term": term, "sung": sung}

    @app.delete("/api/lexicon/{term}")
    def lexicon_del(term: str):
        S_.db.execute("DELETE FROM lexicon WHERE term=?", (term,))
        return {"ok": True}

    # ------------------------------------------------------------------ songs
    @app.get("/api/songs")
    def songs(archived: int = 0):
        rows = S_.db.all("SELECT * FROM songs WHERE archived=? ORDER BY updated DESC", (archived,))
        for r in rows:
            last = S_.db.one("SELECT id, status, stage, summary, preset, created FROM takes WHERE song_id=? "
                             "ORDER BY created DESC LIMIT 1", (r["id"],))
            draft = S_.db.one("SELECT style, language, bpm FROM drafts WHERE song_id=? ORDER BY created DESC LIMIT 1",
                              (r["id"],))
            r["last_take"], r["draft"] = last, draft
        return rows

    @app.post("/api/songs")
    def song_create(body: dict):
        return service.create_song(S_.db, body.get("title", "Untitled"))

    @app.get("/api/songs/{song_id}")
    def song_get(song_id: str):
        song = S_.db.get("songs", song_id) or _404("song")
        song["draft"] = S_.db.one("SELECT * FROM drafts WHERE song_id=? ORDER BY created DESC LIMIT 1", (song_id,))
        song["takes"] = S_.db.all("SELECT id, status, stage, preset, created, finished, summary, chosen_candidate, error "
                                  "FROM takes WHERE song_id=? ORDER BY created DESC", (song_id,))
        return song

    @app.patch("/api/songs/{song_id}")
    def song_patch(song_id: str, body: dict):
        fields = {k: v for k, v in body.items() if k in ("title", "archived", "meta")}
        S_.db.update("songs", song_id, updated=time.time(), **fields)
        return S_.db.get("songs", song_id)

    @app.post("/api/songs/{song_id}/drafts")
    def draft_save(song_id: str, body: CheckBody):
        S_.db.get("songs", song_id) or _404("song")
        return service.create_draft(S_.db, song_id, body.lyrics, body.fields)

    @app.post("/api/songs/{song_id}/takes")
    def take_create(song_id: str, body: TakeBody):
        S_.db.get("songs", song_id) or _404("song")
        if body.draft_id:
            draft = S_.db.get("drafts", body.draft_id) or _404("draft")
        else:
            draft = service.create_draft(S_.db, song_id, body.lyrics or "", body.fields or {})
        if (draft.get("lint") or {}).get("blocking") and not body.allow_errors:
            raise HTTPException(422, {"message": "Fix the errors in the lyrics/style first (or allow errors).",
                                      "draft_id": draft["id"]})
        options = {"overrides": body.overrides or {}}
        if body.seed is not None:
            options["seed"] = body.seed
        take = service.create_take(S_.db, song_id, draft["id"], body.preset, options)
        job = S_.lane.submit("take", take["id"])
        return {"take": take, "job": job, "draft_id": draft["id"]}

    # ------------------------------------------------------------------ takes, plans, candidates
    @app.get("/api/takes/{take_id}")
    def take_get(take_id: str):
        take = S_.db.get("takes", take_id) or _404("take")
        take["draft"] = S_.db.get("drafts", take["draft_id"])
        take["plans"] = S_.db.all("SELECT * FROM plans WHERE take_id=? ORDER BY created", (take_id,))
        take["candidates"] = S_.db.all("SELECT * FROM candidates WHERE take_id=? ORDER BY created", (take_id,))
        take["jobs"] = S_.db.all("SELECT * FROM jobs WHERE take_id=? ORDER BY created", (take_id,))
        for c in take["candidates"]:
            c["files"] = _files_for(c)
            if c.get("asr"):
                c["asr"] = {k: v for k, v in c["asr"].items() if k != "words"}
        return take

    @app.post("/api/takes/{take_id}/resume")
    def take_resume(take_id: str):
        S_.db.get("takes", take_id) or _404("take")
        return S_.lane.submit("take", take_id)

    @app.post("/api/plans/{plan_id}/render")
    def plan_render(plan_id: str, body: dict):
        plan = S_.db.get("plans", plan_id) or _404("plan")
        return S_.lane.submit("render_plan", plan["take_id"], {"plan_id": plan_id, "n": int(body.get("n", 2))})

    @app.get("/api/plans/{plan_id}/display")
    def plan_display(plan_id: str):
        plan = S_.db.get("plans", plan_id) or _404("plan")
        take = S_.db.get("takes", plan["take_id"])
        draft = S_.db.get("drafts", take["draft_id"])
        song = S_.db.get("songs", take["song_id"])
        return _display(plan["abc"], draft, song["title"] if song else "", plan.get("analysis") or {})

    @app.get("/api/plans/{plan_id}/notes")
    def plan_notes(plan_id: str, abc: str | None = None):
        """Timed notes for the in-browser sketch player (no soundfont needed)."""
        plan = S_.db.get("plans", plan_id) or _404("plan")
        score, error = try_parse(plan["abc"] or "")
        if score is None:
            raise HTTPException(422, error)
        from .analysis.metrics import QUALITY_TONES, parse_chord

        def notes(ns):
            return [[round(score.q2s(n.onset), 4), round(score.q2s(n.dur), 4), n.pitch] for n in ns]
        timeline = score.chord_timeline() + [(score.quarters, None)]
        chords = []
        for (t, sym), (t2, _) in zip(timeline, timeline[1:]):
            c = parse_chord(sym) if sym else None
            if c:
                root = 48 + c["root"]
                chords.append([round(score.q2s(t), 4), round(score.q2s(t2 - t), 4), sym,
                               [root + iv for iv in QUALITY_TONES[c["quality"]]],
                               36 + (c["bass"] if c["bass"] is not None else c["root"])])
        return {"bpm": score.bpm, "seconds": score.seconds, "vocal": notes(score.vocal), "ins": notes(score.ins),
                "chords": chords, "beats": [round(score.q2s(q), 4) for q in range(int(score.quarters) + 1)],
                "sections": [{"index": s.index, "name": s.name, "start": score.q2s(s.start), "end": score.q2s(s.end)}
                             for s in score.sections]}

    @app.post("/api/plans/{plan_id}/repair")
    def plan_repair(plan_id: str, body: dict):
        plan = S_.db.get("plans", plan_id) or _404("plan")
        take = S_.db.get("takes", plan["take_id"])
        draft = S_.db.get("drafts", take["draft_id"])
        ops = body.get("ops") or []
        result = apply_ops(plan["abc"], ops, key_hint=(plan.get("analysis") or {}).get("key"))
        if not result["ok"]:
            raise HTTPException(422, result)
        analysis = analyze(result["abc"], draft["lyrics"], gender=draft.get("gender") or "female",
                           requested_bpm=draft.get("bpm"), vocal_bpm=draft.get("vocal_bpm"), lexicon=S_.db.lexicon(),
                           instrumental=draft.get("gender") == "none")
        preview = {"abc": result["abc"], "ops": result["applied"], "diff": result.get("diff"), "analysis": analysis}
        if body.get("preview", False):
            return preview
        count = S_.db.one("SELECT COUNT(*) AS n FROM plans WHERE take_id=?", (take["id"],))["n"]
        row = S_.db.insert("plans", {"take_id": take["id"], "parent_id": plan_id, "idx": count, "source": "edited",
                                     "seed": plan["seed"], "abc": result["abc"], "analysis": analysis,
                                     "score": analysis.get("score"), "passed": int(bool(analysis.get("passed"))),
                                     "edit_ops": result["applied"], "truncated": 0})
        S_.bus.publish("plan", take_id=take["id"], plan_id=row["id"], idx=count, score=row["score"],
                       passed=bool(row["passed"]), source="edited")
        return {**preview, "plan": S_.db.get("plans", row["id"])}

    @app.post("/api/candidates/{cand_id}/finalize")
    def cand_finalize(cand_id: str, body: dict):
        cand = S_.db.get("candidates", cand_id) or _404("candidate")
        if cand["stage"] == "rejected":
            raise HTTPException(409, "This take was rejected before rendering")
        return S_.lane.submit("finalize", cand["take_id"], {"candidate_id": cand_id, "noise_seed": body.get("noise_seed"),
                                                            "steps": body.get("steps")})

    @app.post("/api/candidates/{cand_id}/feedback")
    def cand_feedback(cand_id: str, body: dict):
        cand = S_.db.get("candidates", cand_id) or _404("candidate")
        return S_.db.insert("feedback", {"candidate_id": cand_id, "take_id": cand["take_id"],
                                         "kind": body.get("kind", "issue"), "data": body.get("data") or {}})

    @app.get("/api/candidates/{cand_id}/feedback")
    def cand_feedback_list(cand_id: str):
        return S_.db.all("SELECT * FROM feedback WHERE candidate_id=? ORDER BY created", (cand_id,))

    @app.delete("/api/feedback/{fid}")
    def feedback_delete(fid: str):
        S_.db.execute("DELETE FROM feedback WHERE id=?", (fid,))
        return {"ok": True}

    @app.get("/api/files/{cand_id}/{kind}")
    def file_get(cand_id: str, kind: str, download: int = 0):
        cand = S_.db.get("candidates", cand_id) or _404("candidate")
        path = _files_for(cand, paths=True).get(kind)
        if not path or not Path(path).exists():
            _404("file")
        song = S_.db.one("SELECT s.title FROM songs s JOIN takes t ON t.song_id=s.id WHERE t.id=?", (cand["take_id"],))
        name = f"{(song or {}).get('title', 'song')}-{kind}{Path(path).suffix}"
        return FileResponse(path, filename=name if download else None,
                            media_type={".flac": "audio/flac", ".mp3": "audio/mpeg", ".lrc": "text/plain",
                                        ".abc": "text/plain", ".mid": "audio/midi", ".json": "application/json"}
                            .get(Path(path).suffix, "application/octet-stream"))

    @app.get("/api/jobs")
    def jobs():
        return {"queue": S_.lane.queue(), "current": S_.lane.current,
                "recent": S_.db.all("SELECT * FROM jobs ORDER BY created DESC LIMIT 30")}

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: str):
        return {"ok": S_.lane.cancel(job_id)}

    @app.get("/api/events")
    async def events(request: Request):
        last = int(request.headers.get("last-event-id") or request.query_params.get("since") or 0)
        return StreamingResponse(S_.bus.stream(last), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/diagnostics")
    def diagnostics():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("system.json", json.dumps(system(), indent=2, default=str))
            z.writestr("settings.json", json.dumps(S_.db.settings(), indent=2))
            z.writestr("jobs.json", json.dumps(S_.db.all("SELECT * FROM jobs ORDER BY created DESC LIMIT 200"),
                                               indent=2, default=str))
            for take in S_.db.all("SELECT id, song_id FROM takes ORDER BY created DESC LIMIT 20"):
                recipe = S_.data_dir / "songs" / take["song_id"] / "takes" / take["id"]
                for f in recipe.rglob("recipe.json"):
                    z.write(f, f"recipes/{take['id']}-{f.parent.parent.name}.json")
            log_path = S_.data_dir / "logs" / "studio.log"
            if log_path.exists():
                z.write(log_path, "studio.log")
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": "attachment; filename=yue-studio-diagnostics.zip"})

    # ------------------------------------------------------------------ SPA
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = STATIC / path
        if path and target.is_file() and STATIC in target.resolve().parents:
            return FileResponse(target)
        index = STATIC / "index.html"
        if index.exists():
            return FileResponse(index)
        return HTMLResponse("<h1>YuE Studio</h1><p>The UI has not been built yet: run <code>npm run build</code> "
                            "in <code>web/</code>.</p>")

    return app


def _warmup():
    """Load the pinyin/OpenCC dictionaries now so the first lint in the editor is instant."""
    try:
        service.check("[Verse]\n你好 world 2024\n", {}, {})
    except Exception:  # pragma: no cover
        log.exception("warmup failed")


def _404(what):
    raise HTTPException(404, f"{what} not found")


def _files_for(cand: dict, paths: bool = False) -> dict:
    out = {}
    if cand.get("audio_audition"):
        out["audition"] = cand["audio_audition"]
    if cand.get("audio_final"):
        out["final"] = cand["audio_final"]
        folder = Path(cand["audio_final"]).parent / "export"
        for kind, name in (("master", "master.flac"), ("mp3", "master.mp3"), ("lrc", "lyrics.lrc"),
                           ("abc", "score.abc"), ("midi", "score.mid"), ("recipe", "recipe.json")):
            if (folder / name).exists():
                out[kind] = str(folder / name)
    if paths:
        return out
    return {k: f"/api/files/{cand['id']}/{k}" for k in out}


def _display(abc: str, draft: dict, title: str, analysis: dict) -> dict:
    score, error = try_parse(abc or "")
    if score is None:
        return {"abc": None, "error": error}
    opts = SungOptions(lexicon=S_.db.lexicon())
    doc = parse_lyrics(draft["lyrics"])
    units = F.lyric_units(doc.expanded(), lambda t: max(1, S.count(sing_line(t, opts)[0])))
    sung = {li.index: S.units(sing_line(li.text, opts)[0]) for li in doc.sung_lines}
    labels = {s["index"]: s["tag"] for s in analysis.get("sections", []) if s.get("tag")}
    return {"abc": display.build(score, units, sung, title, labels), "bpm": score.bpm, "key": score.key,
            "seconds": score.seconds}


def configure_logging(data_dir: Path, verbose: bool = False):
    from logging.handlers import RotatingFileHandler

    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data_dir / "logs" / "studio.log", maxBytes=5_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
