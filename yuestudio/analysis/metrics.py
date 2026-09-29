"""Score metrics: harmony (B3), repetition (B1/A17), melody (B4), contrast (B2),
range (A8), phrase-end blow-up risk (A15) and humming risk (A16)."""
from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher
from fractions import Fraction
from statistics import median

from ..abc.score import Note, Score

QUALITY_TONES = {
    "": (0, 4, 7), "m": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8), "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11),
    "m7": (0, 3, 7, 10), "dim7": (0, 3, 6, 9), "m7b5": (0, 3, 6, 10), "sus4": (0, 5, 7), "sus2": (0, 2, 7),
    "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9), "7sus4": (0, 5, 7, 10), "m(maj7)": (0, 3, 7, 11),
}
PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
RE_CHORD = re.compile(r"^([A-G](?:bb|##|b|#)?)(m\(maj7\)|maj7|m7b5|dim7|7sus4|m7|m6|dim|aug|sus4|sus2|m|7|6)?(?:/([A-G](?:bb|##|b|#)?))?$")
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)
DIATONIC_MAJOR = {0: {"", "maj7", "6", "sus2", "sus4"}, 2: {"m", "m7", "sus2", "sus4", "7sus4"}, 4: {"m", "m7"},
                  5: {"", "maj7", "6", "sus2"}, 7: {"", "7", "sus4", "7sus4", "6"}, 9: {"m", "m7"}, 11: {"dim", "m7b5"}}
DIATONIC_MINOR = {0: {"m", "m7", "m6", "m(maj7)", "sus4", "sus2"}, 2: {"dim", "m7b5"}, 3: {"", "maj7", "aug"},
                  5: {"m", "m7", "m6"}, 7: {"m", "m7", "", "7", "sus4", "7sus4"}, 8: {"", "maj7"}, 10: {"", "7"}}
VOICES = {  # comfortable (lo, hi) and extreme (lo, hi) in MIDI
    "female": ((57, 74), (53, 79)), "male": ((48, 67), (43, 72)),
    "duet": ((50, 72), (45, 77)), "choir": ((50, 72), (45, 77)), "none": ((48, 76), (40, 84)),
}


def pc(name: str) -> int:
    base = PC[name[0]]
    base += name.count("#") - name.count("b")
    return base % 12


def parse_chord(symbol: str):
    m = RE_CHORD.match(symbol.strip())
    if not m:
        return None
    root, quality, bass = m.group(1), m.group(2) or "", m.group(3)
    return {"root": pc(root), "quality": quality, "bass": pc(bass) if bass else None, "symbol": symbol}


def key_info(key: str) -> tuple[int, str]:
    minor = key.endswith("m")
    return pc(key[:-1] if minor else key), "minor" if minor else "major"


def chord_tones(symbol: str) -> set[int]:
    c = parse_chord(symbol)
    if not c:
        return set()
    tones = {(c["root"] + t) % 12 for t in QUALITY_TONES[c["quality"]]}
    if c["bass"] is not None:
        tones.add(c["bass"])
    return tones


def is_diatonic(symbol: str, key: str) -> bool:
    c = parse_chord(symbol)
    if not c:
        return False
    tonic, mode = key_info(key)
    degree = (c["root"] - tonic) % 12
    table = DIATONIC_MAJOR if mode == "major" else DIATONIC_MINOR
    return degree in table and c["quality"] in table[degree]


def scale_pcs(key: str) -> set[int]:
    tonic, mode = key_info(key)
    return {(tonic + s) % 12 for s in (MAJOR_SCALE if mode == "major" else MINOR_SCALE)}


# =========================================================================== harmony (B3)
def bar_progression(score: Score, section_indices: list[int] | None = None) -> list[str]:
    out = []
    for b in score.bars:
        if section_indices is not None and b.section not in section_indices:
            continue
        if b.chords:
            out.append(" ".join(sym for _, sym in b.chords))
        elif out:
            out.append(out[-1])  # chord carries over
    return out


def loop_period(seq: list[str], max_period: int = 8) -> tuple[int | None, float]:
    if len(seq) < 8:
        return None, 0.0
    for p in range(1, max_period + 1):
        pairs = len(seq) - p
        same = sum(1 for i in range(pairs) if seq[i] == seq[i + p])
        if pairs and same / pairs >= 0.9:
            return p, same / pairs
    return None, 0.0


def harmony(score: Score, verse_secs: list[int], chorus_secs: list[int]) -> dict:
    events = score.chord_timeline()
    symbols = [s for _, s in events]
    parsed = [parse_chord(s) for s in symbols]
    if not symbols:
        return {"chords": 0, "unique": 0, "richness": 0.0, "loop_period": None, "whole_song_loop": False,
                "extension_ratio": 0.0, "non_diatonic_ratio": 0.0, "per_bar": 0.0, "verse_chorus_same": False,
                "vocabulary": []}
    ext = sum(1 for c in parsed if c and (c["quality"] not in ("", "m") or c["bass"] is not None)) / len(symbols)
    non_diatonic = sum(1 for s in symbols if not is_diatonic(s, score.key)) / len(symbols)
    bars_with = [b for b in score.bars if b.chords]
    per_bar = len(events) / max(1, len(bars_with))
    seq = bar_progression(score)
    period, _ = loop_period(seq)
    whole = period is not None and period <= 4
    vs, cs = bar_progression(score, verse_secs), bar_progression(score, chorus_secs)
    vc_same = bool(vs and cs) and SequenceMatcher(None, vs, cs).ratio() >= 0.8
    unique = len(set(symbols))
    richness = (min(unique, 9) / 9) * 0.35 + min(ext / 0.4, 1.0) * 0.3 + min(non_diatonic / 0.15, 1.0) * 0.15 \
        + (0.0 if whole else 0.1) + (0.0 if vc_same else 0.1)
    return {"chords": len(symbols), "unique": unique, "vocabulary": sorted(set(symbols)),
            "extension_ratio": round(ext, 3), "non_diatonic_ratio": round(non_diatonic, 3),
            "per_bar": round(per_bar, 2), "loop_period": period, "whole_song_loop": whole,
            "verse_chorus_same": vc_same, "richness": round(richness, 3)}


# =========================================================================== repetition (B1 / A17)
def bar_signature(notes: list[Note], bar_start: Fraction):
    if not notes:
        return None
    first = notes[0].pitch
    return tuple((str(n.onset - bar_start), str(n.dur), n.pitch - first) for n in notes)


def repetition(score: Score) -> dict:
    sigs = [bar_signature(b.vocal, b.start) for b in score.bars]
    nonempty = [s for s in sigs if s is not None]
    longest, run, prev = 1 if nonempty else 0, 1, None
    run_at = None
    for i, s in enumerate(sigs):
        if s is not None and s == prev:
            run += 1
            if run > longest:
                longest, run_at = run, i - run + 1
        else:
            run = 1
        prev = s
    distinct = len(set(nonempty)) / max(1, len(nonempty))
    per_section = {sec.index: [sigs[b] for b in sec.bars if sigs[b] is not None] for sec in score.sections}
    sim = {}
    vocal_secs = [i for i, v in per_section.items() if v]
    for a in vocal_secs:
        for b in vocal_secs:
            if a < b:
                sim[(a, b)] = SequenceMatcher(None, per_section[a], per_section[b]).ratio()
    consecutive_dupes = [b for (a, b), r in sim.items() if b == a + 1 and r >= 0.9]
    return {"distinct_bar_ratio": round(distinct, 3), "longest_identical_run": longest,
            "run_start_bar": run_at, "section_similarity": {f"{a}-{b}": round(r, 3) for (a, b), r in sim.items()},
            "consecutive_duplicate_sections": consecutive_dupes, "_sim": sim}


# =========================================================================== melody (B4) and contrast (B2)
def melody(notes: list[Note]) -> dict:
    if len(notes) < 3:
        return {"range": 0, "leap_ratio": 0.0, "repeat_ratio": 0.0, "rhythm_entropy": 0.0, "bland": False}
    pitches = [n.pitch for n in notes]
    ints = [b - a for a, b in zip(pitches, pitches[1:])]
    leap = sum(1 for i in ints if abs(i) >= 3) / len(ints)
    rep = sum(1 for i in ints if i == 0) / len(ints)
    durs = Counter(str(n.dur) for n in notes)
    total = sum(durs.values())
    entropy = -sum((c / total) * math.log2(c / total) for c in durs.values())
    rng = max(pitches) - min(pitches)
    bland = rng < 7 or (leap < 0.08 and entropy < 1.0) or rep > 0.5
    return {"range": rng, "leap_ratio": round(leap, 3), "repeat_ratio": round(rep, 3),
            "rhythm_entropy": round(entropy, 3), "bland": bland}


def contrast(score: Score, verse_secs: list[int], chorus_secs: list[int]) -> dict:
    def stats(secs):
        notes = [n for n in score.vocal if n.section in secs]
        if not notes:
            return None
        span = sum(float(score.sections[s].end - score.sections[s].start) for s in secs)
        return {"mean": sum(n.pitch for n in notes) / len(notes), "density": len(notes) / max(1.0, span)}

    v, c = stats(verse_secs), stats(chorus_secs)
    if not v or not c:
        return {"available": False}
    lift = c["mean"] - v["mean"]
    return {"available": True, "chorus_lift": round(lift, 2), "density_change": round(c["density"] - v["density"], 3),
            "flat": lift < 1.0 and abs(c["density"] - v["density"]) < 0.15}


# =========================================================================== range (A8)
def vocal_range(score: Score, gender: str = "female") -> dict:
    notes = score.vocal
    if not notes:
        return {"available": False}
    (clo, chi), (xlo, xhi) = VOICES.get(gender, VOICES["none"])
    weights = [float(n.dur) for n in notes]
    med = median(n.pitch for n in notes)
    shift = 0
    if gender == "male" and med >= 64:
        shift = -12  # lead sheets often notate male melodies an octave up
    pitches = [n.pitch + shift for n in notes]
    total = sum(weights)
    above = sum(w for p, w in zip(pitches, weights) if p > chi) / total
    below = sum(w for p, w in zip(pitches, weights) if p < clo) / total
    center = sum(p * w for p, w in zip(pitches, weights)) / total
    target = (clo + chi) / 2
    suggest = int(round(target - center))
    suggest = max(-6, min(6, suggest)) if abs(target - center) >= 2.5 else 0
    return {"available": True, "low": min(pitches), "high": max(pitches), "center": round(center, 1),
            "comfort": [clo, chi], "extreme": [xlo, xhi], "above_comfort": round(above, 3),
            "below_comfort": round(below, 3), "octave_assumption": shift, "suggest_transpose": suggest,
            "too_high": max(pitches) > xhi or above > 0.25, "too_low": min(pitches) < xlo or below > 0.25}


# =========================================================================== A15 / A16 risks per line
def fast_ins_windows(score: Score, window: Fraction = Fraction(5, 2)) -> list[int]:
    fast = [n.onset for n in score.ins if n.dur <= Fraction(1, 4)]
    if not score.bars:
        return []
    total = score.quarters
    counts, t = [], Fraction(0)
    while t < total:
        counts.append(sum(1 for o in fast if t <= o < t + window))
        t += window
    return counts


def line_risks(score: Score, line_notes: list[tuple[int, list[Note]]], syllables: dict[int, int],
               gender: str, baseline_fast: float) -> list[dict]:
    """Per sung line: A15 (high leap ending, rushed tail, instrument burst) and A16
    (melisma / odd sustained pitch)."""
    (clo, chi), _ = VOICES.get(gender, VOICES["none"])
    scale = scale_pcs(score.key)
    chord_at = score.chord_timeline()
    fast = [n for n in score.ins if n.dur <= Fraction(1, 4)]
    out = []
    shift = -12 if gender == "male" and score.vocal and median(n.pitch for n in score.vocal) >= 64 else 0
    song = sorted(n.pitch for n in score.vocal)
    p85 = song[int(len(song) * 0.85)] if song else 127
    for occurrence, (line_id, notes) in enumerate(line_notes):
        if not notes:
            out.append({"line": line_id, "occurrence": occurrence, "empty": True})
            continue
        pitches = [n.pitch for n in notes]
        med = median(pitches)
        last = notes[-1]
        leap = last.pitch - med
        high_end = (last.pitch + shift) > chi and last.dur >= Fraction(1, 2)
        leap_end = last.dur >= Fraction(1, 2) and last.pitch == max(pitches) and (
            leap >= 7 or (leap >= 5 and last.pitch >= p85))
        durs = sorted(float(n.dur) for n in notes)
        mid_dur = durs[len(durs) // 2]
        tail = notes[-3:]
        rushed = len(notes) >= 6 and all(n.dur <= Fraction(1, 4) for n in tail) and mid_dur >= 0.5
        end_q = last.end
        burst_n = sum(1 for n in fast if end_q - Fraction(1, 2) <= n.onset < end_q + 2)
        burst = burst_n >= max(6, 2.5 * baseline_fast + 2)
        syl = syllables.get(line_id, len(notes))
        ratio = len(notes) / max(1, syl)
        odd = []
        for n in notes:
            if n.dur >= 2:
                chord = next((s for t, s in reversed(chord_at) if t <= n.onset), None)
                parsed = parse_chord(chord) if chord else None
                clash = parsed is not None and (n.pitch - parsed["root"]) % 12 in (1, 6) \
                    and n.pitch % 12 not in chord_tones(chord)
                if n.pitch % 12 not in scale or clash:  # 9ths, 6ths and suspensions are fine
                    odd.append(float(n.onset))
        out.append({"line": line_id, "occurrence": occurrence, "start": score.q2s(notes[0].onset),
                    "end": score.q2s(end_q), "leap_end": leap_end, "high_end": high_end, "leap": leap,
                    "rushed_tail": rushed, "ins_burst": burst, "burst_notes": burst_n,
                    "notes": len(notes), "syllables": syl, "ratio": round(ratio, 2),
                    "melisma": ratio > 1.8, "cram": ratio < 0.8, "odd_long_notes": odd,
                    "a15": leap_end or high_end or rushed or burst,
                    "a16": ratio > 1.8 or bool(odd)})
    return out
