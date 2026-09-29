"""yue-studio command line: serve | probe | smoke | doctor."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .config import default_data_dir

SAMPLE_LYRICS = """[Intro]

[Verse]
城市的灯火 慢慢亮起来
我走在雨里 想起了你

[Chorus]
我们一起飞 越过这黑夜
不再害怕 不再后退

[Outro]
"""


def _db(args):
    from .db import DB

    data = Path(args.data).expanduser() if args.data else default_data_dir()
    db = DB(data / "studio.db")
    update = {}
    for key in ("mlx_yue_dir", "model_dir", "vae_dir", "precision", "python"):
        value = getattr(args, key, None)
        if value:
            update[key] = value
    if getattr(args, "fake", False):
        update["mode"] = "fake"
    elif update:
        update["mode"] = "real"
    if update:
        db.save_settings({"engine": update})
    return db, data


def cmd_serve(args):
    import uvicorn

    from .app import configure_logging, create_app

    data = Path(args.data).expanduser() if args.data else default_data_dir()
    configure_logging(data, args.verbose)
    app = create_app(data, args.host, args.port, fake=args.fake)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"YuE Studio {url}  (data: {data})")
    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def cmd_doctor(args):
    from .engine.detect import detect

    db, data = _db(args)
    cfg = db.settings()["engine"]
    found = detect(cfg.get("mlx_yue_dir") or None)
    print(json.dumps({"data_dir": str(data), "engine_settings": cfg, "detected": found}, indent=2, ensure_ascii=False))


def cmd_probe(args):
    """Answer the engine questions the harness depends on, on this machine, with this install."""
    from . import repair
    from .engine import Engine
    from .engine.rpc import WorkerError

    db, data = _db(args)
    eng = Engine(data, db.settings)
    out_root = data / "probe" / time.strftime("%Y%m%d-%H%M%S")
    out_root.mkdir(parents=True, exist_ok=True)
    report: dict = {"started": time.time(), "settings": db.settings()["engine"]}

    def step(name, fn):
        t = time.time()
        try:
            value = fn()
            report[name] = {"ok": True, "seconds": round(time.time() - t, 2), **(value or {})}
            print(f"  ✓ {name} ({report[name]['seconds']}s)")
        except Exception as error:
            report[name] = {"ok": False, "seconds": round(time.time() - t, 2), "error": f"{type(error).__name__}: {error}"}
            print(f"  ✗ {name}: {error}")
        return report[name]

    print("YuE Studio probe")
    step("start", lambda: (eng.ensure_started(), {"hello": eng.hello, "caps": eng.caps})[1])
    step("load", lambda: (eng.ensure_loaded(), {"profile": eng.loaded_profile})[1])
    style = "Chinese, pop, female vocal, controlled delivery, 96 BPM"
    ctx: dict = {}

    def plan():
        events = []
        r = eng.call("plan", {"out_dir": str(out_root / "plan"), "style": style, "lyrics": SAMPLE_LYRICS, "seed": 1234,
                              "abc_sampling": {"max_tokens": 4096}}, on_event=events.append)
        from .abc.score import try_parse

        score, err = try_parse(r["abc"] or "")
        ctx["plan"] = r
        return {"abc_tokens": r["abc_tokens"], "truncated": r["truncated"], "timing": r["timing"],
                "bars": len(score.bars) if score else None, "parse_error": err,
                "abc_tokens_per_bar": round(r["abc_tokens"] / len(score.bars), 2) if score else None,
                "section_names": [s.name for s in score.sections] if score else None,
                "progress_events": len(events), "abc_head": (r["abc"] or "")[:400]}

    step("plan", plan)

    def semantic(seed=77, max_tokens=300, name="sem"):
        chunks = []
        r = eng.call("semantic", {"out_dir": str(out_root / name), "plan_dir": ctx["plan"]["plan_dir"], "seed": seed,
                                  "sampling": {"max_tokens": max_tokens, "min_tokens": min(200, max_tokens - 1)}},
                     on_event=lambda m: chunks.append(len(m.get("chunk", []))) if m.get("ev") == "tokens" else None)
        ctx[name] = r
        return {"n_tokens": r["n_tokens"], "truncated": r["truncated"], "timing": r["timing"],
                "streamed_tokens": sum(chunks), "tok_per_s": round(r["n_tokens"] / max(1e-6, (r["timing"] or {})
                                                                                         .get("seconds", 0) or 1e-6), 1)}

    if report.get("plan", {}).get("ok"):
        step("semantic", semantic)
        step("determinism", lambda: (semantic(name="sem2"), {
            "same_tokens": __import__("numpy").load(ctx["sem"]["tokens_path"]).tolist() ==
            __import__("numpy").load(ctx["sem2"]["tokens_path"]).tolist()})[1])

        def render(steps):
            ev = []
            r = eng.call("render", {"out_dir": str(out_root / f"r{steps}"), "plan_dir": ctx["plan"]["plan_dir"],
                                    "tokens_path": ctx["sem"]["tokens_path"], "seed": 77, "ode_steps": steps,
                                    "noise_seed": 77}, on_event=ev.append)
            return {"seconds_audio": r["seconds"], "timing": r["timing"], "nar_progress_events":
                    sum(1 for e in ev if e.get("phase") == "nar"), "audio": r["audio_path"],
                    "nar_s_per_audio_s": round(r["timing"]["nar_seconds"] / max(0.1, r["seconds"]), 3)}

        if report.get("semantic", {}).get("ok"):
            step("render_8", lambda: render(8))
            step("render_32", lambda: render(32))

        def cancel_latency():
            result = {}

            def later():
                time.sleep(2.0)
                t = time.time()
                eng.cancel(grace=20)
                result["latency"] = round(time.time() - t, 2)
            threading.Thread(target=later, daemon=True).start()
            try:
                semantic(seed=5, max_tokens=3000, name="sem_cancel")
                result["cancelled"] = False
            except WorkerError as error:
                result["cancelled"] = error.code == "CANCELLED"
                result["code"] = error.code
            time.sleep(0.5)
            return result

        step("cancel", cancel_latency)

        def edits():
            abc = ctx["plan"]["abc"]
            results = {}
            for label, ops in {"transpose+2": [{"op": "transpose", "semitones": 2}],
                               "tempo88": [{"op": "tempo", "bpm": 88}],
                               "reharm_color": [{"op": "reharmonize", "level": "color"}],
                               "reharm_rich": [{"op": "reharmonize", "level": "rich"}],
                               "duplicate_section1": [{"op": "duplicate_section", "section": 1}],
                               "smooth_endings": [{"op": "smooth_endings"}]}.items():
                r = repair.apply_ops(abc, ops)
                if not r["ok"]:
                    results[label] = {"applied": False, "error": r["error"]}
                    continue
                chk = eng.call("abc_check", {"abc": r["abc"], "compare_to": abc,
                                             "allow_tempo_change": label == "tempo88"})
                try:
                    p = eng.call("plan", {"out_dir": str(out_root / f"edit_{label}"), "style": style,
                                          "lyrics": SAMPLE_LYRICS, "seed": 1234, "abc": r["abc"]})
                    results[label] = {"lyra_parse": chk.get("ok"), "compare": (chk.get("compare") or {}).get("match"),
                                      "engine_plan_tokens": p["abc_tokens"]}
                except WorkerError as error:
                    results[label] = {"lyra_parse": chk.get("ok"), "engine_plan_error": str(error)}
            return {"edits": results}

        step("abc_edits", edits)
    report["engine_info"] = eng.info()
    eng.shutdown()
    path = out_root / "probe-report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    cal = {}
    if report.get("plan", {}).get("abc_tokens_per_bar"):
        cal["abc_tokens_per_bar"] = report["plan"]["abc_tokens_per_bar"]
    if report.get("render_32", {}).get("ok"):
        cal["nar_s_per_audio_s_32"] = report["render_32"]["nar_s_per_audio_s"]
    if cal:
        db.save_settings({"calibration": cal})
    print(f"\nReport: {path}")
    ok = all(v.get("ok", True) for v in report.values() if isinstance(v, dict) and "ok" in v)
    sys.exit(0 if ok else 1)


def cmd_smoke(args):
    """A Draft song end to end (plan, take, audition, master, exports)."""
    from . import service
    from .asr import ASR
    from .director.pipeline import Director
    from .engine import Engine
    from .jobs.bus import Bus

    db, data = _db(args)
    bus, eng = Bus(), Engine(data, db.settings)
    director = Director(db, eng, bus, data, db.settings, ASR(db.settings))
    song = service.create_song(db, "Smoke test")
    draft = service.create_draft(db, song["id"], SAMPLE_LYRICS, {"genres": ["pop"], "bpm": 96})
    take = service.create_take(db, song["id"], draft["id"], args.preset)
    last = {"stage": None}

    def show(e):
        if e.get("topic") == "take" and e.get("stage") != last["stage"]:
            last["stage"] = e.get("stage")
            print(f"  … {e.get('stage')}: {e.get('detail', '')}")
    bus_publish = bus.publish

    def publish(topic, **payload):
        seq = bus_publish(topic, **payload)
        show({"topic": topic, **payload})
        return seq
    bus.publish = publish
    t = time.time()
    try:
        director.run_take(take["id"], threading.Event())
    finally:
        eng.shutdown()
    tk = db.get("takes", take["id"])
    print(json.dumps({"status": tk["status"], "seconds": round(time.time() - t, 1),
                      "exports": (tk.get("summary") or {}).get("exports")}, indent=2, ensure_ascii=False))


def main(argv=None):
    p = argparse.ArgumentParser(prog="yue-studio", description="YuE Studio: quality harness for YuE2")
    p.add_argument("--data", help="data folder (default: ~/Library/Application Support/YuE Studio)")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the studio (default)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open the browser")
    s.add_argument("--fake", action="store_true", help="use the built-in fake engine (development)")
    s.add_argument("--verbose", action="store_true")
    for name, fn in (("probe", cmd_probe), ("smoke", cmd_smoke), ("doctor", cmd_doctor)):
        c = sub.add_parser(name)
        c.add_argument("--mlx-yue", dest="mlx_yue_dir")
        c.add_argument("--model", dest="model_dir")
        c.add_argument("--vae", dest="vae_dir")
        c.add_argument("--precision", choices=("bf16", "8bit", "4bit"))
        c.add_argument("--python")
        c.add_argument("--fake", action="store_true")
        if name == "smoke":
            c.add_argument("--preset", default="draft")
        c.set_defaults(fn=fn)
    s.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    if not args.cmd:
        args = p.parse_args(["serve", "--open", *(argv or [])])
    args.fn(args)


if __name__ == "__main__":
    main()
