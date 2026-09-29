"""Light-weight audio features with numpy/scipy only (no librosa/numba).

All analysis runs on a 16 kHz mono copy. Frames: 1024 window, 320 hop (20 ms).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import soundfile as sf
from scipy import signal

SR = 16000
HOP = 320
WIN = 1024


@dataclass
class Features:
    sr: int
    hop: int
    mono: np.ndarray            # 16 kHz mono
    stereo48: np.ndarray        # original stereo
    rms_db: np.ndarray          # per frame
    centroid: np.ndarray        # Hz per frame
    flux: np.ndarray            # onset strength per frame
    vocal_ratio: np.ndarray     # 150-4000 Hz energy share per frame
    f0: np.ndarray | None = None
    voiced: np.ndarray | None = None

    @property
    def seconds(self) -> float:
        return len(self.mono) / self.sr

    def frame(self, t: float) -> int:
        return int(max(0, min(len(self.rms_db) - 1, t * self.sr / self.hop)))

    def times(self) -> np.ndarray:
        return np.arange(len(self.rms_db)) * self.hop / self.sr


def load(path: str) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    return audio, sr


def to_mono16k(audio: np.ndarray, sr: int) -> np.ndarray:
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    if sr == SR:
        return mono.astype(np.float32)
    g = np.gcd(SR, sr)
    return signal.resample_poly(mono, SR // g, sr // g).astype(np.float32)


def stft_mag(x: np.ndarray) -> np.ndarray:
    pad = np.pad(x, (WIN // 2, WIN // 2))
    n = 1 + (len(pad) - WIN) // HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = pad[idx] * np.hanning(WIN)[None, :].astype(np.float32)
    return np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)


def extract(path: str, pitch: bool = True) -> Features:
    stereo, sr = load(path)
    mono = to_mono16k(stereo, sr)
    mag = stft_mag(mono)
    freqs = np.fft.rfftfreq(WIN, 1 / SR)
    power = mag ** 2
    energy = power.sum(axis=1) + 1e-12
    rms = np.sqrt(energy / (WIN * WIN / 2))
    rms_db = 20 * np.log10(rms + 1e-9)
    centroid = (power * freqs[None, :]).sum(axis=1) / energy
    diff = np.diff(np.log1p(mag), axis=0, prepend=np.log1p(mag[:1]))
    flux = np.maximum(diff, 0).sum(axis=1)
    band = (freqs >= 150) & (freqs <= 4000)   # singing fundamentals + formants; excludes kick/bass/cymbals
    vocal_ratio = power[:, band].sum(axis=1) / energy
    feats = Features(SR, HOP, mono, stereo, rms_db.astype(np.float32), centroid.astype(np.float32),
                     flux.astype(np.float32), vocal_ratio.astype(np.float32))
    if pitch:
        feats.f0, feats.voiced = yin(mono)
    return feats


def yin(x: np.ndarray, fmin: float = 80.0, fmax: float = 900.0, threshold: float = 0.2):
    """Vectorised YIN pitch tracker -> (f0 Hz per frame, voiced bool per frame)."""
    tau_min, tau_max = int(SR / fmax), int(SR / fmin)
    w = WIN
    pad = np.pad(x, (0, w + tau_max))
    n = 1 + (len(x)) // HOP
    f0 = np.zeros(n, dtype=np.float32)
    voiced = np.zeros(n, dtype=bool)
    block = 512
    for b0 in range(0, n, block):
        idx = np.arange(b0, min(n, b0 + block))
        frames = np.stack([pad[i * HOP:i * HOP + w + tau_max] for i in idx])
        # difference function via FFT autocorrelation
        size = 1 << int(np.ceil(np.log2(2 * (w + tau_max))))
        spec = np.fft.rfft(frames, size, axis=1)
        acf = np.fft.irfft(spec * np.conj(np.fft.rfft(frames[:, :w], size, axis=1)), size, axis=1)[:, :tau_max + 1]
        sq = np.cumsum(frames ** 2, axis=1)
        e0 = sq[:, w - 1][:, None]
        taus = np.arange(tau_max + 1)
        e_tau = sq[:, np.minimum(taus + w - 1, sq.shape[1] - 1)] - np.where(taus > 0, sq[:, taus - 1], 0)
        d = e0 + e_tau - 2 * acf
        d[:, 0] = 0
        cum = np.cumsum(d[:, 1:], axis=1) / np.arange(1, tau_max + 1)[None, :]
        dn = np.ones_like(d)
        dn[:, 1:] = d[:, 1:] / (cum + 1e-9)
        region = dn[:, tau_min:]
        below = region < threshold
        first = np.where(below.any(axis=1), below.argmax(axis=1), region.argmin(axis=1))
        best = first + tau_min
        conf = dn[np.arange(len(idx)), best]
        loud = e0[:, 0] / w > 1e-5
        f0[idx] = np.where(loud, SR / np.maximum(best, 1), 0)
        voiced[idx] = (conf < threshold) & loud
    return f0, voiced


def hz_to_midi(f):
    return 69 + 12 * np.log2(np.maximum(f, 1e-6) / 440.0)
