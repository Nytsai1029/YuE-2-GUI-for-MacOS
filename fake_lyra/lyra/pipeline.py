"""Fake lyra.pipeline.YuE2Pipeline with the same staged surface as mlx-Yue.

Timing knobs (env):
  YUESTUDIO_FAKE_TOKS      AR tokens per second (default 4000)
  YUESTUDIO_FAKE_NAR_S     seconds for a full NAR pass (default 1.5)
  YUESTUDIO_FAKE_LOAD_S    load seconds (default 0.3)
Faults (YUESTUDIO_FAKE_FAULTS): see _composer.py and _render.py, plus
  sem_loop (repeat a span of semantic tokens), crash_nar (hard exit in NAR),
  oom_semantic (raise a memory error), hang_nar (sleep forever).
"""
from __future__ import annotations

import hashlib
import os
import random
import time
from pathlib import Path

import numpy as np
from yue2.pipeline import SemanticResult, SymbolicPlan
from yue2.protocol import (
    ABC_END,
    ABC_START,
    CONTEXT,
    FakeTokenizer,
    GenerationConfig,
    SongRequest,
    resolve_sampling,
    token_prefixes,
)

from ._composer import compose, faults
from .music_tools.abc_tools import parse


def initial_noise(frames, seed):
    return np.random.Generator(np.random.PCG64(seed)).standard_normal((frames, 64), dtype=np.float32)


def _env(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


class YuE2Pipeline:
    def __init__(self, model_dir, vae_dir, *, precision="bf16", generation_config=None, progress=False, **kwargs):
        for path in (model_dir, vae_dir):
            if not Path(path).expanduser().exists():
                raise FileNotFoundError(f"Model path does not exist: {path}")
        self.model_dir, self.vae_dir = Path(model_dir), Path(vae_dir)
        self.precision = precision
        self.generation_config = generation_config or GenerationConfig()
        self.tokenizer = FakeTokenizer()
        self.query_chunk_size = 256
        self.weights = {"mot": {"fake": True, "precision": precision}, "vae": {"fake": True}}
        self.runtime = {"fake": True}
        self._closed = False
        time.sleep(_env("YUESTUDIO_FAKE_LOAD_S", 0.3))

    @classmethod
    def from_pretrained(cls, model="vanch007/mlx-Yue2-3B", *, vae="m-a-p/YuE2-Vae", converted_dir=None,
                        local_files_only=False, precision="bf16", progress=True, **kwargs):
        return cls(model, vae, precision=precision, progress=progress,
                   generation_config=kwargs.get("generation_config"))

    # ------------------------------------------------------------ internals mirrored from mlx-Yue
    def _check_execution(self):
        if self._closed:
            raise RuntimeError("YuE2Pipeline is closed")

    def _guarded_cancelled(self, cancelled):
        def guarded():
            self._check_execution()
            return False if cancelled is None else cancelled()
        return guarded

    def _load_model(self, for_nar=False):
        return self

    def _stream(self, n, cancelled, on_token, phase, tokens=None):
        rate = _env("YUESTUDIO_FAKE_TOKS", 4000)
        start = time.perf_counter()
        for i in range(n):
            if cancelled is not None and cancelled():
                raise InterruptedError("Cancelled during generation")
            if on_token is not None:
                on_token(phase, tokens[i] if tokens is not None else 0)
            if rate > 0 and i % 50 == 49:
                behind = (i + 1) / rate - (time.perf_counter() - start)
                if behind > 0:
                    time.sleep(behind)
        return time.perf_counter() - start

    # ------------------------------------------------------------ stages
    def plan(self, style=None, lyrics=None, *, tags=None, request=None, abc_sampling=None,
             cancelled=None, on_token=None, **kwargs):
        request = request or SongRequest(style=style or tags, lyrics=lyrics, **kwargs)
        if request.abc is not None:
            ids = self.tokenizer.encode(request.abc)
            return SymbolicPlan(request, request.abc, ids, token_prefixes(request, self.tokenizer, ids),
                                {"seconds": 0.0, "output_tokens": 0, "external_prefix_tokens": len(ids)})
        sampling = resolve_sampling(abc_sampling, self.generation_config.abc)
        if "stdout_noise" in faults():  # libraries printing progress bars must not corrupt the RPC channel
            print("Planning score:  42%|####      | 1234/4096 [00:12<00:30]")
            os.write(1, b"raw fd-1 write from a C extension\n")
        abc = compose(request.style, request.lyrics, request.seed)
        ids = self.tokenizer.encode(abc)
        truncated = len(ids) > sampling.max_tokens
        ids = ids[: sampling.max_tokens]
        seconds = self._stream(len(ids), cancelled, on_token, "abc", ids)
        text = self.tokenizer.decode(ids)
        return SymbolicPlan(request, text, ids, token_prefixes(request, self.tokenizer, ids),
                            {"seconds": seconds, "output_tokens": len(ids)}, truncated)

    def generate_semantic(self, plan, *, sampling=None, cancelled=None, on_token=None):
        sampling = resolve_sampling(sampling, self.generation_config.semantic)
        active = faults()
        rng = random.Random(plan.request.seed)
        if "oom_semantic" in active:
            raise MemoryError("Resource guard: MLX active memory exceeded budget (fake)")
        tokens = self._fake_tokens(plan, rng)
        if "sem_loop" in active and rng.random() < active["sem_loop"]:
            a = int(len(tokens) * 0.4)
            span = tokens[a:a + 200]
            tokens = tokens[:a + 200] + span * 2 + tokens[a + 200:]
        truncated = len(tokens) > sampling.max_tokens
        tokens = tokens[: sampling.max_tokens]
        if len(plan.prefix) + len(tokens) > CONTEXT:
            raise ValueError("Prefix + requested generation budget exceeds 24576; no implicit truncation")
        seconds = self._stream(len(tokens), cancelled, on_token, "semantic", tokens)
        return SemanticResult(plan, tokens, {"seconds": seconds, "output_tokens": len(tokens)}, truncated)

    def _fake_tokens(self, plan, rng):
        """Tokens follow the ABC bar by bar: identical bars give near-identical tokens."""
        if plan.abc is None:
            return [rng.randrange(32768) for _ in range(4500)]
        score = parse(plan.abc)
        spq = 60.0 / score.bpm
        vocal, ins = score.voices["Vocal"], score.voices["Ins"]
        tokens = []
        for start, length, _meter in vocal.bars:
            end = start + length
            content = [n for n in vocal.notes if start <= n[0] < end] + [n for n in ins.notes if start <= n[0] < end]
            chord = [c for t, c in vocal.chords if start <= t < end]
            digest = hashlib.sha256(repr((content and [(float(o - start), p, float(d)) for o, p, d in content], chord))
                                    .encode()).digest()
            base = int.from_bytes(digest[:4], "big")
            frames = int(round(float(length) * spq / 0.04))
            for f in range(frames):
                value = (base + f * 7919) % 32768
                if rng.random() < 0.08:
                    value = rng.randrange(32768)
                tokens.append(value)
        return tokens or [0] * 200

    def synthesize(self, semantic, *, cancelled=None, noise=None):
        from .nar import synthesize

        return synthesize(self, semantic.plan.prefix, semantic.tokens, semantic.plan.request.seed,
                          steps=self.generation_config.ode_steps, context=self.generation_config.context,
                          cancelled=self._guarded_cancelled(cancelled), on_progress=None, noise=noise)

    def decode(self, latents, *, full=False, vae=None, cancelled=None):
        from ._render import render

        frames = latents.shape[0]
        n = 1920 * frames - 64
        prefix = getattr(self, "_last_prefix", None)
        if prefix is None:
            return np.zeros((n, 2), dtype=np.float32)
        abc, lyrics = self._unpack_prefix(prefix)
        seed = getattr(self, "_last_seed", 0)
        if abc is None:
            return (np.random.default_rng(seed).standard_normal((n, 2)) * 0.01).astype(np.float32)
        return np.clip(render(abc, lyrics, n, seed), -1, 1)

    def _unpack_prefix(self, prefix):
        try:
            a = prefix.index(ABC_START)
            b = prefix.index(ABC_END)
        except ValueError:
            return None, ""
        text = self.tokenizer.decode(prefix[1:a])
        abc = self.tokenizer.decode(prefix[a + 1:b]) if b > a + 1 else None
        lyrics = text.split("[Lyrics]\n", 1)[-1]
        return abc, lyrics

    def close(self):
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
