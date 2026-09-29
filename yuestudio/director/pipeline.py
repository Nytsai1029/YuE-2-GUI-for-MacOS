"""The Director: runs one take through plan -> analyze -> choose -> semantic -> gates ->
audition -> checks -> rank -> finalize, persisting every step so a crash or restart
resumes from the last finished stage.

Budget-aware: presets are upper bounds; the Director stops as soon as a plan/take
passes every gate with a comfortable score.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from pathlib import Path

from .. import export
from ..abc.score import parse as parse_score
from ..align import coverage as asr_coverage
from ..analysis.metrics import scale_pcs
from ..analysis.plan import analyze
from ..audio import features as AF
from ..audio import metrics as AM
from ..audio.master import master
from ..checks.semantic import FRAME, LoopDetector, length_gate
from ..engine.rpc import WorkerError
from ..lyrics.doc import parse as parse_lyrics
from ..lyrics.duration import budgets, estimate
from . import presets, ranking

log = logging.getLogger("yuestudio.director")


class Cancelled(Exception):
    pass


class Director:
    def __init__(self, db, engine, bus, data_dir: Path, settings_fn, asr=None):
        self.db, self.engine, self.bus = db, engine, bus
        self.data_dir = Path(data_dir)
        self.settings_fn = settings_fn
        self.asr = asr

    # ================================================================== helpers
    def take_dir(self, take: dict) -> Path:
        return self.data_dir / "songs" / take["song_id"] / "takes" / take["id"]

    def _progress(self, take_id: str, stage: str, detail: str = "", done=None, total=None, eta=None, **extra):
        progress = {"stage": stage, "detail": detail, "done": done, "total": total, "eta": eta, "t": time.time(), **extra}
        self.db.update("takes", take_id, stage=stage, progress=progress)
        self.bus.publish("take", take_id=take_id, **progress)

    @staticmethod
    def _check(cancel: threading.Event):
        if cancel.is_set():
            raise Cancelled()

    def _calibration(self) -> dict:
        return self.settings_fn()["calibration"]

    def _learn(self, key: str, value: float, alpha: float = 0.3):
        if not value or value <= 0:
            return
        cal = self._calibration()
        old = cal.get(key)
        cal[key] = round(value if not old else (1 - alpha) * old + alpha * value, 4)
        self.db.save_settings({"calibration": cal})

    def eta_semantic(self, seconds: float) -> float:
        return seconds / FRAME / (self._calibration().get("ar_tok_s") or 60.0)

    def eta_render(self, seconds: float, steps: int) -> float:
        rtf32 = self._calibration().get("nar_s_per_audio_s_32") or 1.2
        return seconds * rtf32 * steps / 32 + 5

    def _job_dir(self, take: dict, *parts) -> Path:
        path = self.take_dir(take).joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ================================================================== entry points
    def run_take(self, take_id: str, cancel: threading.Event) -> None:
        take = self.db.get("takes", take_id)
        draft = self.db.get("drafts", take["draft_id"])
        cfg = presets.resolve(take["preset"], (take.get("options") or {}).get("overrides"))
        self.db.update("takes", take_id, status="running", error=None)
        try:
            plans = self._plans(take, draft, cfg, cancel)
            ranked = sorted(plans, key=lambda p: (bool(p["passed"]), p["score"] or 0), reverse=True)
            best = None
            for attempt, plan in enumerate(ranked[:cfg["max_plan_attempts"]]):  # noqa: B007
                self.db.update("takes", take_id, chosen_plan=plan["id"])
                self.bus.publish("take", take_id=take_id, stage="plan_chosen", plan_id=plan["id"], attempt=attempt)
                cands = self._takes_for_plan(take, draft, plan, cfg, cancel, cfg["takes"])
                good = [c for c in cands if c["stage"] == "audition" and all((c.get("gates") or {}).values())]
                if good:
                    best = max(good, key=lambda c: c["score"] or 0)
                    break
                if cands and best is None:
                    best = max((c for c in cands if c["stage"] == "audition"), key=lambda c: c["score"] or 0,
                               default=None)
            if best is None:
                raise RuntimeError("Every take was rejected by the gates (loops, truncation or wrong length). "
                                   "Check the lyrics lint and try again or use a different preset.")
            self.db.update("takes", take_id, chosen_candidate=best["id"])
            self._finalize(take, draft, best, cfg["final_steps"], cancel)
            self._finish(take_id, "done")
        except Cancelled:
            self._finish(take_id, "cancelled")
        except Exception as error:
            log.exception("take %s failed", take_id)
            self._finish(take_id, "failed", error)
            raise

    def run_render_plan(self, take_id: str, plan_id: str, n: int, cancel: threading.Event) -> None:
        """User picked (or edited) a plan: render ``n`` takes of it, then finalize the best."""
        take = self.db.get("takes", take_id)
        draft = self.db.get("drafts", take["draft_id"])
        cfg = presets.resolve(take["preset"], (take.get("options") or {}).get("overrides"))
        plan = self.db.get("plans", plan_id)
        self.db.update("takes", take_id, status="running", chosen_plan=plan_id, error=None)
        try:
            cands = self._takes_for_plan(take, draft, plan, cfg, cancel, n, fresh=True)
            done = [c for c in cands if c["stage"] == "audition"]
            if not done:
                raise RuntimeError("Every take of this plan was rejected by the gates.")
            best = max(done, key=lambda c: (all((c.get("gates") or {}).values()), c["score"] or 0))
            self.db.update("takes", take_id, chosen_candidate=best["id"])
            self._finalize(take, draft, best, cfg["final_steps"], cancel)
            self._finish(take_id, "done")
        except Cancelled:
            self._finish(take_id, "cancelled")
        except Exception as error:
            self._finish(take_id, "failed", error)
            raise

    def run_finalize(self, take_id: str, candidate_id: str, cancel: threading.Event, noise_seed=None,
                     steps: int | None = None) -> None:
        take = self.db.get("takes", take_id)
        draft = self.db.get("drafts", take["draft_id"])
        cfg = presets.resolve(take["preset"])
        cand = self.db.get("candidates", candidate_id)
        self.db.update("takes", take_id, status="running", chosen_candidate=candidate_id, error=None)
        try:
            self._finalize(take, draft, cand, steps or cfg["final_steps"] or 32, cancel, noise_seed=noise_seed,
                           force=True)
            self._finish(take_id, "done")
        except Cancelled:
            self._finish(take_id, "cancelled")
        except Exception as error:
            self._finish(take_id, "failed", error)
            raise

    def _finish(self, take_id: str, status: str, error: Exception | None = None):
        err = None
        if error is not None:
            err = {"type": type(error).__name__, "message": getattr(error, "message", None) or str(error),
                   "code": getattr(error, "code", None)}
        self.db.update("takes", take_id, status=status, finished=time.time(), error=err,
                       stage="done" if status == "done" else status)
        self.bus.publish("take", take_id=take_id, stage=status, status=status, error=err)

    # ================================================================== plans
    def _budgets(self, draft: dict, predicted: float | None = None) -> dict:
        doc = parse_lyrics(draft["lyrics"])
        ratio = (draft.get("bpm") or 96) / (draft.get("vocal_bpm") or draft.get("bpm") or 96)
        instrumental = draft.get("gender") == "none" and not draft.get("mapping")
        if instrumental:
            doc = parse_lyrics(draft["sung"])
        est = estimate(doc, draft.get("vocal_bpm") or draft.get("bpm") or 96, sung_text=draft["sung"],
                       style=draft["style"], abc_tokens_per_bar=self._calibration().get("abc_tokens_per_bar") or 44,
                       drum_ratio=ratio, instrumental=instrumental)
        return budgets(est, predicted)

    def _plans(self, take: dict, draft: dict, cfg: dict, cancel) -> list[dict]:
        plans = self.db.all("SELECT * FROM plans WHERE take_id=? AND analysis IS NOT NULL ORDER BY idx", (take["id"],))
        base = int((take.get("options") or {}).get("seed") or random.randrange(1, 2**31))
        for k in range(len(plans), cfg["plans"]):
            self._check(cancel)
            if len(plans) >= cfg["min_plans"] and cfg["plan_accept"]:
                best = max(plans, key=lambda p: (bool(p["passed"]), p["score"] or 0))
                if best["passed"] and (best["score"] or 0) >= cfg["plan_accept"]:
                    self._progress(take["id"], "plan", f"plan {k} is good enough; skipping the rest", k, cfg["plans"])
                    break
            plans.append(self._generate_plan(take, draft, k, base + 1009 * k, cfg["plans"]))
        return plans

    def _generate_plan(self, take, draft, idx, seed, total, abc=None, parent=None, source="generated") -> dict:
        row = self.db.insert("plans", {"take_id": take["id"], "idx": idx, "seed": seed, "source": source,
                                       "parent_id": parent})
        out_dir = self._job_dir(take, "plans", row["id"])
        budget = self._budgets(draft)
        abc_max = budget["abc_max_tokens"]
        expected = budget["abc_max_tokens"] / 1.35
        start = time.time()

        def on_event(msg):
            if msg.get("ev") == "progress" and msg.get("phase") == "abc":
                done = msg.get("done") or 0
                rate = done / max(0.1, time.time() - start)
                self._progress(take["id"], "plan", f"Writing score {idx + 1}/{total}", done, int(expected),
                               eta=max(0, (expected - done) / max(1, rate)), plan_index=idx)

        self._progress(take["id"], "plan", f"Writing score {idx + 1}/{total}", 0, int(expected), plan_index=idx)
        for _attempt in range(2):
            out = self.engine.call("plan", {"out_dir": str(out_dir), "style": draft["style"], "lyrics": draft["sung"],
                                            "cot": "full", "seed": seed, "abc": abc,
                                            "abc_sampling": {"max_tokens": abc_max}}, on_event=on_event)
            if not out["truncated"] or abc is not None:
                break
            abc_max = int(abc_max * 1.6)  # the score ran out of room: re-plan with a bigger budget
            self.bus.publish("take", take_id=take["id"], stage="plan", detail="score was cut off; retrying larger")
        timing = out.get("timing") or {}
        if timing.get("output_tokens") and timing.get("seconds"):
            self._learn("ar_tok_s", timing["output_tokens"] / timing["seconds"])
        edit_ops = []
        if draft.get("gender") == "none" and out.get("abc"):
            out, edit_ops = self._instrumentalize(take, draft, out, out_dir, seed)
        target = self.target_seconds(draft)
        analysis = self.analyze(out, draft)
        if target and analysis.get("ok") and abs(analysis["predicted_seconds"] / target - 1) > 0.08:
            out, ops = self._fit_length(take, draft, out, out_dir, seed, target,
                                        analysis.get("alignment", {}).get("extra_abc", []))
            if ops:
                edit_ops += ops
                analysis = self.analyze(out, draft)
        if analysis.get("ok") and analysis.get("bars"):
            self._learn("abc_tokens_per_bar", out["abc_tokens"] / max(1, analysis["bars"]), alpha=0.2)
        self.db.update("plans", row["id"], abc=out["abc"], dir=out["plan_dir"], truncated=int(out["truncated"]),
                       n_tokens=out["abc_tokens"], analysis=analysis, score=analysis.get("score", 0.0),
                       passed=int(bool(analysis.get("passed"))), edit_ops=edit_ops)
        row = self.db.get("plans", row["id"])
        self.bus.publish("plan", take_id=take["id"], plan_id=row["id"], idx=idx, score=row["score"],
                         passed=bool(row["passed"]), scorecard=analysis.get("scorecard"))
        return row

    @staticmethod
    def target_seconds(draft: dict) -> float | None:
        t = (draft.get("style_fields") or {}).get("target_seconds")
        return float(t) if t else None

    def analyze(self, out: dict, draft: dict) -> dict:
        return analyze(out["abc"] or "", draft["lyrics"], gender=draft.get("gender") or "female",
                       requested_bpm=draft.get("bpm"), vocal_bpm=draft.get("vocal_bpm"),
                       truncated=out["truncated"], lexicon=self.db.lexicon(),
                       instrumental=draft.get("gender") == "none", target_seconds=self.target_seconds(draft))

    def _fit_length(self, take, draft, out, out_dir, seed, target, extra):
        """Bring the score to the requested length (instrumental sections + small tempo change)."""
        from ..repair import fit_length

        try:
            abc, info = fit_length(out["abc"], target, extra)
        except Exception as error:
            log.warning("fit_length failed: %s", error)
            return out, []
        if not info["steps"]:
            return out, []
        fixed = self.engine.call("plan", {"out_dir": str(out_dir), "style": draft["style"], "lyrics": draft["sung"],
                                          "cot": "full", "seed": seed, "abc": abc})
        fixed["truncated"] = out["truncated"]
        fixed["timing"] = out.get("timing")
        self.bus.publish("take", take_id=take["id"], stage="plan",
                         detail=f"fitted score to target: {info['from_seconds']:.0f}s → {info['to_seconds']:.0f}s")
        return fixed, [{"op": "fit_length", "auto": True, **info}]

    def _instrumentalize(self, take, draft, out, out_dir, seed):
        """YuE2 always writes a singer's part; in instrumental mode move it to the instrument
        line and resubmit the score, so nothing is left for the voice to hum."""
        from ..abc.score import try_parse
        from ..repair import instrumentalize

        score, _ = try_parse(out["abc"])
        if score is None or not score.vocal:
            return out, []
        try:
            abc, info = instrumentalize(out["abc"])
        except Exception as error:  # keep the original; the plan gate will flag the vocal line
            log.warning("instrumentalize failed: %s", error)
            return out, []
        (Path(out_dir) / "score.original.abc").write_text(out["abc"], encoding="utf-8")
        fixed = self.engine.call("plan", {"out_dir": str(out_dir), "style": draft["style"], "lyrics": draft["sung"],
                                          "cot": "full", "seed": seed, "abc": abc})
        fixed["truncated"] = out["truncated"]
        fixed["timing"] = out.get("timing")
        self.bus.publish("take", take_id=take["id"], stage="plan",
                         detail=f"moved {info['moved_to_instrument']} vocal notes to the instrument line")
        return fixed, [{"op": "instrumentalize", "auto": True, **info}]

    def ensure_engine_plan(self, take: dict, draft: dict, plan: dict) -> dict:
        """Edited/imported plans exist only as ABC text until they are rendered."""
        if plan.get("dir") and Path(plan["dir"]).exists():
            return plan
        out_dir = self._job_dir(take, "plans", plan["id"])
        out = self.engine.call("plan", {"out_dir": str(out_dir), "style": draft["style"], "lyrics": draft["sung"],
                                        "cot": "full", "seed": plan["seed"], "abc": plan["abc"]})
        self.db.update("plans", plan["id"], dir=out["plan_dir"], n_tokens=out["abc_tokens"])
        return self.db.get("plans", plan["id"])

    # ================================================================== takes (semantic + audition)
    def _takes_for_plan(self, take, draft, plan, cfg, cancel, n, fresh=False) -> list[dict]:
        plan = self.ensure_engine_plan(take, draft, plan)
        existing = [] if fresh else self.db.all(
            "SELECT * FROM candidates WHERE plan_id=? AND stage IN ('audition','final','rejected') ORDER BY idx",
            (plan["id"],))
        cands = list(existing)
        offset = self.db.one("SELECT COUNT(*) AS n FROM candidates WHERE plan_id=?", (plan["id"],))["n"]
        predicted = (plan.get("analysis") or {}).get("predicted_seconds") or 180.0
        for m in range(len(existing), n):
            self._check(cancel)
            good = [c for c in cands if c["stage"] == "audition" and all((c.get("gates") or {}).values())]
            if len(good) >= cfg["min_takes"] and cfg["take_accept"] and \
                    max(c["score"] or 0 for c in good) >= cfg["take_accept"]:
                break
            seed = (plan["seed"] * 31 + 7919 * (offset + m + 1)) % (2**62)
            cand = self._semantic(take, draft, plan, offset + m, seed, predicted, cancel, m, n)
            if cand["stage"] != "rejected":
                cand = self._audition(take, draft, plan, cand, cfg["audition_steps"], cfg, cancel, m, n)
            cands.append(cand)
        return cands

    def _semantic(self, take, draft, plan, idx, seed, predicted, cancel, m, n) -> dict:
        cand = self.db.insert("candidates", {"take_id": take["id"], "plan_id": plan["id"], "idx": idx,
                                             "sem_seed": seed, "noise_seed": seed, "stage": "semantic"})
        out_dir = self._job_dir(take, "candidates", cand["id"])
        budget = self._budgets(draft, predicted)
        detector = LoopDetector()
        state = {"loop": None, "aborted": False, "start": time.time(), "n": 0}
        expected = predicted / FRAME
        label = f"Singing take {m + 1}/{n}"

        def on_event(msg):
            if msg.get("ev") == "tokens":
                state["n"] = msg["start"] + len(msg["chunk"])
                loop = detector.feed(msg["chunk"])
                if loop and not state["aborted"]:
                    state["loop"], state["aborted"] = loop, True
                    try:  # non-blocking: this runs on the worker's reader thread
                        self.engine.worker.send("cancel", {"target": msg["id"]})
                    except Exception:
                        pass
            elif msg.get("ev") == "progress" and msg.get("phase") == "semantic":
                done = msg.get("done") or 0
                rate = done / max(0.1, time.time() - state["start"])
                self._progress(take["id"], "semantic", label, done, int(expected),
                               eta=max(0, (expected - done) / max(1, rate)), rate=round(rate, 1), candidate_id=cand["id"])
                if cancel.is_set() and not state["aborted"]:
                    state["aborted"] = True
                    try:
                        self.engine.worker.send("cancel", {"target": msg["id"]})
                    except Exception:
                        pass

        self._progress(take["id"], "semantic", label, 0, int(expected), eta=self.eta_semantic(predicted),
                       candidate_id=cand["id"])
        try:
            out = self.engine.call("semantic", {"out_dir": str(out_dir), "plan_dir": plan["dir"], "seed": seed,
                                                "sampling": {"max_tokens": budget["semantic_max_tokens"]}},
                                   on_event=on_event)
        except WorkerError as error:
            if error.code == "CANCELLED" and state["loop"] is not None:
                loop = state["loop"].to_dict()
                self.db.update("candidates", cand["id"], stage="rejected", reject_reason="loop",
                               gates={"no_loop": False}, metrics={"loop": loop})
                self.bus.publish("candidate", take_id=take["id"], candidate_id=cand["id"], stage="rejected",
                                 reason="loop", loop=loop)
                return self.db.get("candidates", cand["id"])
            if error.code == "CANCELLED":
                raise Cancelled() from error
            raise
        if out.get("timing", {}).get("seconds"):
            self._learn("ar_tok_s", out["n_tokens"] / out["timing"]["seconds"])
        length = length_gate(out["n_tokens"], predicted, out["truncated"])
        tokens = __import__("numpy").load(out["tokens_path"]).tolist()
        loop = detector.found or LoopDetector().feed(tokens)
        gates = ranking.take_gates(length, loop.to_dict() if loop else None, None)
        stage = "semantic" if gates["not_truncated"] and gates["no_loop"] and length["ratio"] >= 0.6 else "rejected"
        reason = None if stage != "rejected" else ("truncated" if not gates["not_truncated"] else
                                                   "loop" if loop else "short")
        self.db.update("candidates", cand["id"], tokens_path=out["tokens_path"], n_tokens=out["n_tokens"],
                       truncated=int(out["truncated"]), stage=stage, reject_reason=reason, gates=gates,
                       metrics={"length": length, "loop": loop.to_dict() if loop else None})
        self.bus.publish("candidate", take_id=take["id"], candidate_id=cand["id"], stage=stage, reason=reason,
                         length=length)
        return self.db.get("candidates", cand["id"])

    def _audition(self, take, draft, plan, cand, steps, cfg, cancel, m, n) -> dict:
        out_dir = self._job_dir(take, "candidates", cand["id"], f"s{steps}")
        seconds = cand["n_tokens"] * FRAME
        label = f"Rendering take {m + 1}/{n} (preview quality)"
        self._progress(take["id"], "render", label, 0, steps, eta=self.eta_render(seconds, steps),
                       candidate_id=cand["id"])
        out = self._render(take, cand, plan, out_dir, steps, cand["noise_seed"], label, cancel)
        self._check(cancel)
        self._progress(take["id"], "check", f"Checking take {m + 1}/{n}", candidate_id=cand["id"])
        checks = self.check_audio(draft, plan, cand, out["audio_path"], cfg.get("asr_passes", 1))
        metrics = dict(cand.get("metrics") or {})
        metrics.update(checks["metrics"])
        self.db.update("candidates", cand["id"], stage="audition", audio_audition=out["audio_path"],
                       gates=checks["gates"], metrics=metrics, asr=checks["asr"], score=checks["score"])
        cand = self.db.get("candidates", cand["id"])
        self.bus.publish("candidate", take_id=take["id"], candidate_id=cand["id"], stage="audition",
                         score=cand["score"], gates=cand["gates"], card=metrics.get("card"))
        return cand

    def _render(self, take, cand, plan, out_dir, steps, noise_seed, label, cancel) -> dict:
        start = time.time()
        eta0 = self.eta_render(cand["n_tokens"] * FRAME, steps)

        def on_event(msg):
            if msg.get("ev") == "progress" and msg.get("phase") in ("nar", "decode"):
                done, total = msg.get("done") or 0, msg.get("total") or steps
                elapsed = time.time() - start
                eta = elapsed / done * (total - done) if done else eta0
                self._progress(take["id"], "render", label, done, total, eta=eta, candidate_id=cand["id"],
                               phase=msg.get("phase"))
            if cancel.is_set():
                try:
                    self.engine.worker.send("cancel", {"target": msg["id"]})
                except Exception:
                    pass

        try:
            out = self.engine.call("render", {"out_dir": str(out_dir), "plan_dir": plan["dir"],
                                              "tokens_path": cand["tokens_path"], "seed": cand["sem_seed"],
                                              "ode_steps": steps, "noise_seed": noise_seed}, on_event=on_event)
        except WorkerError as error:
            if error.code == "CANCELLED":
                raise Cancelled() from error
            raise
        nar = (out.get("timing") or {}).get("nar_seconds")
        if nar and out.get("seconds"):
            self._learn("nar_s_per_audio_s_32", nar / out["seconds"] * 32 / steps)
        return out

    # ================================================================== checks
    def check_audio(self, draft: dict, plan: dict, cand: dict, audio_path: str, asr_passes: int = 1) -> dict:
        analysis = plan.get("analysis") or {}
        predicted = analysis.get("predicted_seconds")
        feats = AF.extract(audio_path)
        audio = AM.song_metrics(feats, 48000, predicted)
        lines = [{"line": ln["line"], "start": ln["start"], "end": ln["end"]}
                 for ln in (analysis.get("alignment") or {}).get("lines", []) if ln["end"] > ln["start"]]
        asr_result, words = None, []
        instrumental = draft.get("gender") == "none" and not draft.get("mapping")
        if instrumental and self.asr is not None and self.asr.available():
            runs = self.asr.transcribe(audio_path, passes=1) or []
            heard = [w for r in runs for w in r["words"] if w.get("prob", 0) > 0.5 and len(w["text"].strip(" .,!?♪")) > 1]
            asr_result = {"available": True, "instrumental": True, "coverage": 1.0, "lines": [], "skipped": [],
                          "repeated": [], "words_heard": len(heard), "words": heard[:200]}
        elif self.asr is not None and self.asr.available():
            runs = self.asr.transcribe(audio_path, language=draft.get("language") if draft.get("language") in
                                       ("zh", "en") else None, passes=asr_passes)
            if runs:
                occurrences = [{"line": mp["display_index"], "text": mp["sung"]} for mp in (draft.get("mapping") or [])]
                results = [asr_coverage(occurrences, r["words"]) for r in runs]
                asr_result = max(results, key=lambda r: r["coverage"])
                words = runs[results.index(asr_result)]["words"]
                asr_result["words"] = words
                timed = {p["occurrence"]: p for p in asr_result["lines"] if p["start"] is not None}
                for i, ln in enumerate(lines):  # refine windows with what was actually heard
                    if i in timed and timed[i]["end"] > timed[i]["start"]:
                        ln["start"], ln["end"] = timed[i]["start"], timed[i]["end"]
        a15 = AM.phrase_events(feats, lines)
        key = analysis.get("key")
        a16 = AM.hum_events(feats, lines, words, scale_pcs(key) if key else None) if words else []
        events = {"a15": a15, "a16": a16, "lines": len(lines)}
        metrics_prev = cand.get("metrics") or {}
        length = metrics_prev.get("length") or {}
        loop = metrics_prev.get("loop")
        card = ranking.take_card(analysis.get("scorecard") or {}, length, loop, audio, events, asr_result)
        gates = ranking.take_gates(length, loop, asr_result)
        return {"metrics": {"audio": audio, "events": events, "card": card["card"], "penalty": card["penalty"]},
                "gates": gates, "asr": asr_result, "score": card["score"]}

    # ================================================================== finalize
    def _finalize(self, take, draft, cand, final_steps, cancel, noise_seed=None, force=False):
        plan = self.db.get("plans", cand["plan_id"])
        plan = self.ensure_engine_plan(take, draft, plan)
        seed = cand["noise_seed"] if noise_seed is None else int(noise_seed)
        audio = cand.get("audio_audition")
        if final_steps and (force or final_steps != (self.settings_fn()["quality"].get("audition_steps") or 8)):
            out_dir = self._job_dir(take, "candidates", cand["id"], f"final_s{final_steps}_n{seed}")
            label = f"Final render ({final_steps} steps)"
            self._progress(take["id"], "finalize", label, 0, final_steps,
                           eta=self.eta_render(cand["n_tokens"] * FRAME, final_steps), candidate_id=cand["id"])
            out = self._render(take, cand, plan, out_dir, final_steps, seed, label, cancel)
            audio = out["audio_path"]
        self._check(cancel)
        self._progress(take["id"], "export", "Mastering and exporting", candidate_id=cand["id"])
        exports = self.export(take, draft, plan, cand, audio, noise_seed=seed, steps=final_steps)
        metrics = dict(self.db.get("candidates", cand["id"]).get("metrics") or {})
        if exports.get("mastering"):
            metrics["master"] = exports["mastering"]
        self.db.update("candidates", cand["id"], stage="final", audio_final=audio, audio_master=exports.get("master"),
                       noise_seed=seed, metrics=metrics)
        summary = {"candidate_id": cand["id"], "plan_id": plan["id"], "exports": exports, "score": cand["score"]}
        self.db.update("takes", take["id"], summary=summary)
        self.bus.publish("candidate", take_id=take["id"], candidate_id=cand["id"], stage="final", exports=exports)

    def export(self, take, draft, plan, cand, audio_path, noise_seed=None, steps=None) -> dict:
        settings = self.settings_fn()
        song = self.db.get("songs", take["song_id"])
        title = song["title"] if song else "YuE Studio"
        folder = Path(audio_path).parent / "export"
        folder.mkdir(parents=True, exist_ok=True)
        out = {"raw": audio_path}
        ms = settings["mastering"]
        metrics = (cand.get("metrics") or {}).get("audio") or {}
        dst = folder / "master.flac"
        fields = draft.get("style_fields") or {}
        max_seconds = float(fields["target_seconds"]) if fields.get("exact_length") and fields.get("target_seconds") else None
        if ms.get("enabled", True) or max_seconds:
            out["mastering"] = master(audio_path, str(dst), lufs=ms.get("lufs", -14), true_peak=ms.get("true_peak", -1),
                                      fade_out=1.5 if metrics.get("abrupt_ending") else 0.3, max_seconds=max_seconds,
                                      normalize=ms.get("enabled", True))
        else:
            import shutil

            shutil.copyfile(audio_path, dst)
        export.tag_flac(str(dst), title)
        out["master"] = str(dst)
        if export.mp3(str(dst), str(folder / "master.mp3"), title):
            out["mp3"] = str(folder / "master.mp3")
        lines = self.lyric_times(draft, plan, cand)
        (folder / "lyrics.lrc").write_text(export.lrc(lines, title), encoding="utf-8")
        out["lrc"] = str(folder / "lyrics.lrc")
        if plan.get("abc"):
            (folder / "score.abc").write_text(plan["abc"], encoding="utf-8")
            out["abc"] = str(folder / "score.abc")
            try:
                export.midi(parse_score(plan["abc"]), str(folder / "score.mid"))
                out["midi"] = str(folder / "score.mid")
            except Exception:
                log.exception("MIDI export failed")
        export.recipe(str(folder / "recipe.json"), {
            "harness": __import__("yuestudio").__version__, "title": title, "created": time.time(),
            "draft": {k: draft.get(k) for k in ("lyrics", "style", "style_fields", "sung", "bpm", "vocal_bpm",
                                                "gender", "language")},
            "plan": {"id": plan["id"], "seed": plan["seed"], "source": plan["source"], "abc": plan["abc"]},
            "candidate": {"id": cand["id"], "semantic_seed": cand["sem_seed"], "noise_seed": noise_seed,
                          "final_steps": steps, "n_tokens": cand["n_tokens"]},
            "engine": {"profile": self.engine.loaded_profile, "caps": self.engine.caps},
            "disclosure": export.DISCLOSURE})
        out["recipe"] = str(folder / "recipe.json")
        return out

    def lyric_times(self, draft, plan, cand) -> list[dict]:
        display = draft["lyrics"].split("\n")
        asr = cand.get("asr") or {}
        heard = {p["occurrence"]: p["start"] for p in asr.get("lines", []) if p.get("start") is not None}
        planned = (plan.get("analysis") or {}).get("alignment", {}).get("lines", [])
        out = []
        for i, ln in enumerate(planned):
            start = heard.get(i, ln["start"])
            if 0 <= ln["line"] < len(display):
                out.append({"text": display[ln["line"]], "start": start})
        return out
