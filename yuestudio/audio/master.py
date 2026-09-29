"""Light mastering for delivery: DC removal, edge fades, loudness normalisation and a
true-peak safety limiter. The raw render is always kept next to the master."""
from __future__ import annotations

import numpy as np
import soundfile as sf
from scipy import signal

from .metrics import integrated_lufs, true_peak_db


def _fade(x: np.ndarray, sr: int, seconds: float, at_end: bool) -> np.ndarray:
    n = min(len(x), int(seconds * sr))
    if n <= 1:
        return x
    curve = np.sin(np.linspace(0, np.pi / 2, n)) ** 2
    y = x.copy()
    if at_end:
        y[-n:] *= curve[::-1, None]
    else:
        y[:n] *= curve[:, None]
    return y


def _limit(x: np.ndarray, sr: int, ceiling_db: float) -> np.ndarray:
    """Look-ahead peak limiter on a 4x oversampled envelope (gentle, transparent)."""
    ceiling = 10 ** (ceiling_db / 20)
    env = np.abs(signal.resample_poly(x, 4, 1, axis=0)).max(axis=1).reshape(-1, 4).max(axis=1)[:len(x)]
    gain = np.minimum(1.0, ceiling / np.maximum(env, 1e-9))
    held = _min_filter(gain, int(0.005 * sr))              # 5 ms look-ahead: instant attack
    r = np.exp(-1.0 / (0.08 * sr))                         # 80 ms release
    released = signal.lfilter([1 - r], [1, -r], held, zi=[held[0] * r])[0]
    return x * np.minimum(held, released)[:, None]


def _min_filter(x: np.ndarray, width: int) -> np.ndarray:
    from scipy.ndimage import minimum_filter1d

    return minimum_filter1d(x, size=2 * width + 1, mode="nearest")


def master(src: str, dst: str, lufs: float = -14.0, true_peak: float = -1.0,
           fade_in: float = 0.01, fade_out: float = 0.0) -> dict:
    x, sr = sf.read(src, dtype="float32", always_2d=True)
    x = signal.sosfiltfilt(signal.butter(2, 20, "highpass", fs=sr, output="sos"), x, axis=0).astype(np.float32)
    x = _fade(x, sr, fade_in, at_end=False)
    x = _fade(x, sr, max(0.02, fade_out), at_end=True)
    before = integrated_lufs(x, sr)
    gain = 10 ** ((lufs - before) / 20) if before > -69 else 1.0
    y = (x * min(gain, 10 ** (18 / 20))).astype(np.float32)
    if true_peak_db(y) > true_peak:
        y = _limit(y, sr, true_peak - 0.2).astype(np.float32)
    sf.write(dst, y, sr, subtype="PCM_24")
    return {"input_lufs": round(before, 2), "output_lufs": round(integrated_lufs(y, sr), 2),
            "true_peak_db": round(true_peak_db(y), 2), "gain_db": round(20 * np.log10(max(gain, 1e-9)), 2)}
