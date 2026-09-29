"""Song-level audio checks (B7, B8, C1-C3) and per-line event detectors (A15, A16).

Line windows come from the plan alignment (expected seconds per sung line). When ASR
word timestamps are available they refine the windows and enable the humming check.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from .features import Features, hz_to_midi


# --------------------------------------------------------------------------- loudness (ITU-R BS.1770-4)
def _k_filter(sr):
    """K-weighting: high-shelf pre-filter + RLB high-pass (RBJ biquads, as in pyloudnorm)."""
    fc, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    a = 10 ** (gain / 40.0)
    w0 = 2 * np.pi * fc / sr
    alpha, cw, sa = np.sin(w0) / (2 * q), np.cos(w0), 2 * np.sqrt(a) * np.sin(w0) / (2 * q)
    b1 = [a * ((a + 1) + (a - 1) * cw + sa), -2 * a * ((a - 1) + (a + 1) * cw), a * ((a + 1) + (a - 1) * cw - sa)]
    a1 = [(a + 1) - (a - 1) * cw + sa, 2 * ((a - 1) - (a + 1) * cw), (a + 1) - (a - 1) * cw - sa]
    fc, q = 38.13547087602444, 0.5003270373238773
    w0 = 2 * np.pi * fc / sr
    alpha, cw = np.sin(w0) / (2 * q), np.cos(w0)
    b2 = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
    a2 = [1 + alpha, -2 * cw, 1 - alpha]
    return (np.array(b1) / a1[0], np.array(a1) / a1[0]), (np.array(b2) / a2[0], np.array(a2) / a2[0])


def integrated_lufs(stereo: np.ndarray, sr: int) -> float:
    (b1, a1), (b2, a2) = _k_filter(sr)
    y = signal.lfilter(b2, a2, signal.lfilter(b1, a1, stereo, axis=0), axis=0)
    block, step = int(0.4 * sr), int(0.1 * sr)
    if len(y) < block:
        return -70.0
    powers = np.array([np.mean(y[i:i + block] ** 2, axis=0).sum() for i in range(0, len(y) - block, step)])
    loud = -0.691 + 10 * np.log10(powers + 1e-12)
    gated = powers[loud > -70]
    if not len(gated):
        return -70.0
    rel = -0.691 + 10 * np.log10(gated.mean()) - 10
    gated = powers[(loud > -70) & (loud > rel)]
    return float(-0.691 + 10 * np.log10(gated.mean() + 1e-12))


def true_peak_db(stereo: np.ndarray) -> float:
    up = signal.resample_poly(stereo, 4, 1, axis=0)
    return float(20 * np.log10(np.abs(up).max() + 1e-12))


# --------------------------------------------------------------------------- song level
def song_metrics(f: Features, sr48: int, expected_seconds: float | None = None) -> dict:
    x = f.stereo48
    peak = float(np.abs(x).max())
    clip_ratio = float(np.mean(np.abs(x) >= 0.999))
    dc = float(np.abs(x.mean(axis=0)).max())
    corr = float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) if x.shape[1] == 2 and x[:, 0].std() > 0 else 1.0
    rms = f.rms_db
    active = rms > -45
    times = f.times()
    lead = float(times[np.argmax(active)]) if active.any() else f.seconds
    trail = float(f.seconds - times[len(active) - 1 - np.argmax(active[::-1])]) if active.any() else f.seconds
    gaps = _silent_gaps(rms, times, -50, 2.0)
    med = float(np.median(rms[active])) if active.any() else -60.0
    tail_n = max(1, int(1.5 * f.sr / f.hop))
    tail = rms[-tail_n:]
    last = rms[-max(1, int(0.2 * f.sr / f.hop)):]
    abrupt = bool(float(np.mean(tail)) > med - 6 and float(np.mean(last)) > med - 10)
    out = {"seconds": round(f.seconds, 2), "peak_db": round(20 * np.log10(peak + 1e-12), 2),
           "clip_ratio": round(clip_ratio, 6), "dc_offset": round(dc, 5), "stereo_correlation": round(corr, 3),
           "lead_silence": round(lead, 2), "trail_silence": round(trail, 2), "gaps": gaps,
           "lufs": round(integrated_lufs(x, sr48), 2), "abrupt_ending": abrupt, "median_rms_db": round(med, 2)}
    if expected_seconds:
        out["length_ratio"] = round(f.seconds / expected_seconds, 3)
    return out


def _silent_gaps(rms, times, floor_db, min_len):
    gaps, start = [], None
    for t, v in zip(times, rms):
        if v < floor_db and start is None:
            start = t
        elif v >= floor_db and start is not None:
            if t - start >= min_len and start > 1.0:
                gaps.append([round(float(start), 2), round(float(t), 2)])
            start = None
    return gaps


# --------------------------------------------------------------------------- A15: phrase-end blow-up
def _seg(arr, f, a, b):
    i, j = f.frame(a), max(f.frame(b), f.frame(a) + 1)
    return arr[i:j]


def phrase_events(f: Features, lines: list[dict]) -> list[dict]:
    """``lines``: [{line, start, end}] in seconds. Returns A15 events per line."""
    times = f.times()
    onset_thr = np.percentile(f.flux, 85) if len(f.flux) else 0
    onsets = times[1:-1][(f.flux[1:-1] > onset_thr) & (f.flux[1:-1] >= f.flux[:-2]) & (f.flux[1:-1] >= f.flux[2:])]
    window = 1.5
    if f.seconds > window:
        counts = np.histogram(onsets, bins=np.arange(0, f.seconds + window, window))[0]
        base = float(np.median(counts)) if len(counts) else 0.0
    else:
        base = 0.0
    out = []
    for ln in lines:
        a, b = ln["start"], ln["end"]
        if b - a < 1.0 or b > f.seconds:
            continue
        cut = b - max(0.6, 0.25 * (b - a))
        body_rms, tail_rms = _seg(f.rms_db, f, a, cut), _seg(f.rms_db, f, cut, b)
        body_c, tail_c = _seg(f.centroid, f, a, cut), _seg(f.centroid, f, cut, b)
        if not len(body_rms) or not len(tail_rms):
            continue
        loud_jump = float(np.percentile(tail_rms, 80) - np.percentile(body_rms, 80))
        bright = float(np.median(tail_c) / (np.median(body_c) + 1e-6))
        after = int(np.sum((onsets >= b) & (onsets < b + window)))
        burst = after >= 6 and after > 2.2 * base + 1
        f0_jump = 0.0
        if f.f0 is not None:
            vb = _seg(f.voiced, f, a, cut)
            vt = _seg(f.voiced, f, cut, b)
            fb, ft = _seg(f.f0, f, a, cut)[vb], _seg(f.f0, f, cut, b)[vt]
            if len(fb) > 5 and len(ft) > 3:
                f0_jump = float(np.median(hz_to_midi(ft)) - np.median(hz_to_midi(fb)))
        signals = {"loud": loud_jump > 6.0, "bright": bright > 1.35, "pitch": f0_jump > 5.0, "burst": burst}
        hit = sum(signals.values()) >= 2 or loud_jump > 9.0
        if hit:
            out.append({"line": ln.get("line"), "start": round(cut, 2), "end": round(min(f.seconds, b + window), 2),
                        "loud_jump_db": round(loud_jump, 1), "brightness": round(bright, 2),
                        "f0_jump": round(f0_jump, 1), "onsets_after": after, "onset_baseline": round(base, 1),
                        "signals": [k for k, v in signals.items() if v]})
    return out


# --------------------------------------------------------------------------- A16: voiced but wordless
def hum_events(f: Features, lines: list[dict], words: list[dict], key_pcs: set[int] | None = None) -> list[dict]:
    """Spans inside expected sung lines that are clearly pitched but carry no ASR words."""
    if f.voiced is None:
        return []
    times = f.times()
    word_mask = np.zeros(len(times), dtype=bool)
    fillers = {"hmm", "mm", "mmm", "hm", "ah", "oh", "ooh", "uh", "la", "嗯", "啊", "哦", "噢", "♪"}
    for w in words:
        if w.get("text", "").strip().lower().strip(".,!?♪ ") in fillers:
            continue
        word_mask[f.frame(w["start"]):f.frame(w["end"]) + 1] = True
    out = []
    for ln in lines:
        a, b = ln["start"], ln["end"]
        i, j = f.frame(a), f.frame(b)
        if j - i < 20:
            continue
        voiced = f.voiced[i:j] & (f.vocal_ratio[i:j] > 0.3)
        wordless = voiced & ~word_mask[i:j]
        share = float(wordless.mean())
        if share > 0.45 and voiced.mean() > 0.3:
            f0s = f.f0[i:j][wordless]
            odd = None
            if key_pcs and len(f0s):
                pcs = np.round(hz_to_midi(f0s)).astype(int) % 12
                odd = float(np.mean([p not in key_pcs for p in pcs]))
            out.append({"line": ln.get("line"), "start": round(a, 2), "end": round(b, 2),
                        "wordless_share": round(share, 2), "out_of_key": None if odd is None else round(odd, 2)})
    return out
