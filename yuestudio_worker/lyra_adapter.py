"""Every call into mlx-Yue (``lyra``) and upstream ``yue2`` lives here.

The worker runs inside the user's own mlx-Yue virtualenv. Nothing is installed there;
we only import what mlx-Yue already ships. Version differences are absorbed in this
file so the rest of the harness sees one stable surface.

Python 3.12, standard library + numpy + soundfile only.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import time
from pathlib import Path

import numpy as np

from .protocol import CONTEXT, SAMPLE_RATE


class Cancelled(Exception):
    pass


class NotLoaded(Exception):
    pass


def _version(name):
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


class LyraAdapter:
    def __init__(self):
        self.pipe = None
        self.profile = None
        self._nar_direct = None  # resolved lazily: can we call lyra.nar.synthesize ourselves?

    # ------------------------------------------------------------------ discovery
    def introspect(self):
        caps = {"lyra": False, "yue2": False, "abc_tools": False, "nar_progress": False,
                "plan_load": False, "versions": {}}
        try:
            import lyra  # noqa: F401

            caps["lyra"] = True
        except Exception as error:  # pragma: no cover - depends on user's venv
            caps["lyra_error"] = repr(error)
            return caps
        try:
            from yue2.pipeline import SymbolicPlan  # noqa: F401

            caps["yue2"] = True
            caps["plan_load"] = hasattr(SymbolicPlan, "load")
        except Exception as error:
            caps["yue2_error"] = repr(error)
        try:
            from lyra.music_tools import abc_tools  # noqa: F401

            caps["abc_tools"] = True
        except Exception as error:
            caps["abc_tools_error"] = repr(error)
        caps["nar_progress"] = self._nar_signature_ok()
        for name in ("mlx-yue", "mlx", "numpy", "yue2"):
            caps["versions"][name] = _version(name)
        try:
            import lyra

            caps["fake"] = bool(getattr(lyra, "__fake__", False))
        except Exception:
            caps["fake"] = False
        return caps

    def _nar_signature_ok(self):
        try:
            from lyra import nar

            params = inspect.signature(nar.synthesize).parameters
            return all(k in params for k in ("steps", "cancelled", "on_progress", "noise"))
        except Exception:
            return False

    # ------------------------------------------------------------------ lifecycle
    def load(self, model, vae, converted_dir=None, precision="8bit", memory_budget_gib=None,
             ode_steps=32, require_ac=False):
        from lyra import YuE2Pipeline

        self.unload()
        kwargs = {"vae": vae, "precision": precision, "local_files_only": True, "progress": False}
        if converted_dir:
            kwargs["converted_dir"] = str(Path(converted_dir).expanduser().resolve())
        if memory_budget_gib:
            kwargs["memory_budget_gib"] = float(memory_budget_gib)
        if require_ac:
            kwargs["require_ac"] = True
        try:
            from yue2.protocol import GenerationConfig

            kwargs["generation_config"] = GenerationConfig(ode_steps=int(ode_steps))
        except Exception:
            pass
        start = time.perf_counter()
        self.pipe = YuE2Pipeline.from_pretrained(str(Path(model).expanduser()), **kwargs)
        self.profile = {"model": str(model), "vae": str(vae), "precision": precision}
        weights = getattr(self.pipe, "weights", {})
        return {"load_seconds": time.perf_counter() - start,
                "weights": json.loads(json.dumps(weights, default=str)),
                "runtime": json.loads(json.dumps(getattr(self.pipe, "runtime", {}), default=str))}

    def unload(self):
        if self.pipe is not None:
            try:
                self.pipe.close()
            except Exception:
                pass
        self.pipe = None
        self.profile = None

    def _require(self):
        if self.pipe is None:
            raise NotLoaded("Engine is not loaded")
        return self.pipe

    # ------------------------------------------------------------------ stages
    def plan(self, out_dir, style, lyrics, cot="full", seed=0, abc=None, abc_sampling=None,
             cfg_scale=None, cancelled=None, on_token=None):
        from yue2.protocol import SongRequest

        pipe = self._require()
        request = SongRequest(style=style, lyrics=lyrics, cot=cot, seed=int(seed), abc=abc,
                              cfg_scale=cfg_scale, id="take")
        self._check_budget(pipe, request, abc_sampling)
        plan = pipe.plan(request=request, abc_sampling=abc_sampling or None,
                         cancelled=cancelled, on_token=on_token)
        out_dir = Path(out_dir)
        plan.save(out_dir)
        return {"plan_dir": str(out_dir), "abc": plan.abc, "abc_tokens": len(plan.abc_ids),
                "prefix_tokens": len(plan.prefix), "truncated": bool(plan.truncated),
                "timing": _jsonable(plan.timing)}

    def _check_budget(self, pipe, request, abc_sampling):
        """Fail early with a clear message instead of deep inside generation."""
        try:
            base = len(pipe.tokenizer.encode(request.text()))
        except Exception:
            return
        abc_max = (abc_sampling or {}).get("max_tokens", 4096)
        if request.abc is None and base + abc_max + 4 > CONTEXT:
            raise ValueError(f"CONTEXT: prompt ({base} tokens) + ABC budget ({abc_max}) exceeds {CONTEXT}")

    def _load_plan(self, plan_dir, seed=None):
        from yue2.pipeline import SymbolicPlan

        plan = SymbolicPlan.load(plan_dir)
        if seed is not None and int(seed) != plan.request.seed:
            plan = dataclasses.replace(plan, request=dataclasses.replace(plan.request, seed=int(seed)))
        return plan

    def semantic(self, out_dir, plan_dir, seed, sampling=None, cancelled=None, on_token=None):
        pipe = self._require()
        plan = self._load_plan(plan_dir, seed)
        sampling = dict(sampling or {})
        max_tokens = sampling.get("max_tokens", 9000)
        clamped = False
        if len(plan.prefix) + max_tokens > CONTEXT:
            room = CONTEXT - len(plan.prefix) - 1
            if room < 500:
                raise ValueError(f"CONTEXT: prefix ({len(plan.prefix)}) leaves no room for audio; exceeds {CONTEXT}")
            sampling["max_tokens"], clamped = room, True
            sampling["min_tokens"] = min(sampling.get("min_tokens", 200), room - 1)
        result = pipe.generate_semantic(plan, sampling=sampling or None, cancelled=cancelled,
                                        on_token=on_token)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        tokens_path = out_dir / "semantic.npy"
        np.save(tokens_path, np.asarray(result.tokens, dtype=np.int32), allow_pickle=False)
        return {"tokens_path": str(tokens_path), "n_tokens": len(result.tokens),
                "truncated": bool(result.truncated), "timing": _jsonable(result.timing),
                "seed": int(plan.request.seed), "budget_clamped": clamped, "prefix_tokens": len(plan.prefix)}

    def render(self, out_dir, plan_dir, tokens_path, seed, ode_steps=32, noise_seed=None,
               cancelled=None, on_progress=None, keep_latents=False):
        import soundfile as sf
        from yue2.pipeline import SemanticResult

        pipe = self._require()
        plan = self._load_plan(plan_dir, seed)
        tokens = [int(t) for t in np.load(tokens_path, allow_pickle=False).tolist()]
        semantic = SemanticResult(plan, tokens, {}, False)
        noise_seed = int(plan.request.seed if noise_seed is None else noise_seed)
        noise = self._noise(len(tokens), noise_seed)
        t0 = time.perf_counter()
        latents = self._synthesize(pipe, semantic, int(ode_steps), noise, cancelled, on_progress)
        t1 = time.perf_counter()
        if on_progress:
            on_progress("decode", 0, 1)
        audio = pipe.decode(latents, cancelled=cancelled)
        audio = np.asarray(audio, dtype=np.float32)
        t2 = time.perf_counter()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_path = out_dir / "audio.flac"
        sf.write(str(audio_path), audio, SAMPLE_RATE, subtype="PCM_24")
        if keep_latents:
            np.save(out_dir / "latents.npy", np.asarray(latents, dtype=np.float32), allow_pickle=False)
        return {"audio_path": str(audio_path), "sample_rate": SAMPLE_RATE,
                "seconds": float(len(audio) / SAMPLE_RATE), "ode_steps": int(ode_steps),
                "noise_seed": noise_seed, "timing": {"nar_seconds": t1 - t0, "vae_seconds": t2 - t1}}

    def _noise(self, frames, seed):
        try:
            from lyra.pipeline import initial_noise

            return initial_noise(frames, seed)
        except Exception:
            return np.random.Generator(np.random.PCG64(seed)).standard_normal((frames, 64), dtype=np.float32)

    def _synthesize(self, pipe, semantic, steps, noise, cancelled, on_progress):
        """Prefer the module-level NAR call (real progress + chosen step count), else swap config."""
        if self._nar_direct is None:
            self._nar_direct = self._nar_signature_ok() and all(
                hasattr(pipe, n) for n in ("_load_model", "_guarded_cancelled", "_check_execution"))
        if self._nar_direct:
            from lyra import nar

            pipe._check_execution()
            model = pipe._load_model(for_nar=True)

            def report(done, total):
                pipe._check_execution()
                if on_progress:
                    on_progress("nar", int(done), int(total))

            kwargs = {"steps": steps, "context": pipe.generation_config.context,
                      "cancelled": pipe._guarded_cancelled(cancelled), "on_progress": report, "noise": noise}
            if "query_chunk_size" in inspect.signature(nar.synthesize).parameters:
                kwargs["query_chunk_size"] = getattr(pipe, "query_chunk_size", None)
            result = nar.synthesize(model, semantic.plan.prefix, semantic.tokens, semantic.plan.request.seed,
                                    **kwargs)
            pipe._check_execution()
            return np.asarray(result, dtype=np.float32)
        old = pipe.generation_config
        try:
            pipe.generation_config = dataclasses.replace(old, ode_steps=steps)
            kwargs = {"cancelled": cancelled}
            if "noise" in inspect.signature(pipe.synthesize).parameters:
                kwargs["noise"] = noise
            return np.asarray(pipe.synthesize(semantic, **kwargs), dtype=np.float32)
        finally:
            pipe.generation_config = old

    # ------------------------------------------------------------------ ABC
    def abc_check(self, abc, compare_to=None, allow_tempo_change=False):
        from lyra.music_tools import abc_tools

        try:
            score = abc_tools.parse(abc)
        except abc_tools.AbcError as error:
            return {"ok": False, "error": str(error)}
        out = {"ok": True, "report": json.loads(json.dumps(abc_tools.report(score), default=str))}
        if compare_to is not None:
            try:
                before = abc_tools.parse(compare_to)
            except abc_tools.AbcError as error:
                return {"ok": False, "error": f"baseline: {error}"}
            out["compare"] = abc_tools.compare(before, score, allow_tempo_change=allow_tempo_change)
        if self.pipe is not None and hasattr(self.pipe, "tokenizer"):
            try:
                out["abc_tokens"] = len(self.pipe.tokenizer.encode(abc))
            except Exception:
                pass
        return out


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))
