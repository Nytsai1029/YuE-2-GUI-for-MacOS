"""Fake lyra.nar.synthesize: same signature as mlx-Yue's module-level NAR call."""
from __future__ import annotations

import os
import random
import time

import numpy as np


def synthesize(model, prefix, tokens, seed, steps=32, context=24576, cancelled=None, on_progress=None,
               noise=None, query_chunk_size=None):
    from ._composer import faults

    active = faults()
    if "crash_nar" in active and random.Random(seed).random() < active["crash_nar"]:
        os._exit(137)  # simulate a hard Metal crash: the process just dies
    if "hang_nar" in active:
        time.sleep(10**6)
    marker = os.environ.get("YUESTUDIO_FAKE_CRASH_ONCE")
    if marker and not os.path.exists(marker):
        open(marker, "w").close()
        os._exit(137)  # crash exactly once: the supervisor must restart and retry
    total = float(os.environ.get("YUESTUDIO_FAKE_NAR_S", "1.5")) * (steps / 32)
    for step in range(steps):
        if cancelled is not None and cancelled():
            raise InterruptedError("Cancelled during acoustic synthesis")
        time.sleep(total / max(1, steps))
        if on_progress is not None:
            on_progress(step + 1, steps)
    frames = len(tokens)
    if noise is None:
        noise = np.random.Generator(np.random.PCG64(seed)).standard_normal((frames, 64), dtype=np.float32)
    model._last_prefix = list(prefix)
    model._last_seed = int(seed)
    return (noise * 0.5).astype(np.float32)
