"""Toy "planner" for the fake engine: lyrics -> native two-voice YuE2 ABC.

It writes the same dialect the real model emits (validated by the vendored
abc_tools.parse). Failure modes can be injected so the harness's detectors can be
exercised on a laptop:

    YUESTUDIO_FAKE_FAULTS="repeat_section,cram:0.5,leap_end"

Plan-level faults: skip_section, repeat_section, cram, melisma, leap_end, busy_ins,
loop, simple (always I-V-vi-IV). Audio-level faults live in _render.py.
"""
from __future__ import annotations

import os
import random
import re

from .music_tools.abc_tools import key_accidentals

LETTERS = "CDEFGAB"
MAJOR_KEYS = ["C", "G", "D", "F", "Bb", "A", "Eb", "E"]
PROGRESSIONS = [
    [0, 4, 5, 3],      # I V vi IV  (the "too simple" default)
    [5, 3, 0, 4],      # vi IV I V
    [0, 5, 3, 4],      # I vi IV V
    [3, 4, 2, 5],      # IV V iii vi
    [0, 2, 3, 4],      # I iii IV V
]
SECTION_COMMENT = {"intro": "interlude", "interlude": "interlude", "outro": "interlude",
                   "verse": "verse", "pre-chorus": "verse", "chorus": "chorus", "bridge": "bridge"}
ALLOWED = [16, 12, 8, 6, 4, 3, 2, 1]


def faults():
    spec = os.environ.get("YUESTUDIO_FAKE_FAULTS", "")
    out = {}
    for item in filter(None, (s.strip() for s in spec.split(","))):
        name, _, prob = item.partition(":")
        out[name] = float(prob) if prob else 1.0
    return out


def count_syllables(line):
    cjk = len(re.findall(r"[㐀-鿿]", line))
    latin = 0
    for word in re.findall(r"[A-Za-z']+", line):
        groups = re.findall(r"[aeiouy]+", word.lower())
        n = len(groups) - (1 if word.lower().endswith("e") and len(groups) > 1 else 0)
        latin += max(1, n)
    return max(1, cjk + latin)


def parse_lyrics(lyrics):
    sections, current = [], None
    for raw in lyrics.splitlines():
        line = raw.strip()
        tag = re.fullmatch(r"\[([^\]]+)\]", line)
        if tag:
            current = {"tag": tag.group(1).strip().lower(), "lines": []}
            sections.append(current)
        elif line:
            if current is None:
                current = {"tag": "verse", "lines": []}
                sections.append(current)
            current["lines"].append(line)
    return sections


def split_units(units):
    out = []
    while units > 0:
        step = next(a for a in ALLOWED if a <= units)
        out.append(step)
        units -= step
    return out


class Writer:
    """Accumulates bars for both voices and emits 1-4 bar groups."""

    def __init__(self, key, tonic_index):
        self.key = key
        self.tonic_index = tonic_index
        self.acc = key_accidentals(key)
        self.groups = []  # (comment|None, [vocal bars], [ins bars])

    def note(self, degree, units, tie=False):
        absolute = self.tonic_index + degree  # diatonic steps from C4
        octave, letter = divmod(absolute, 7)
        name = LETTERS[letter]
        if octave <= 3:
            text = name + "," * (4 - octave)
        elif octave == 4:
            text = name
        else:
            text = name.lower() + "'" * (octave - 5)
        return f"{text}{units if units != 1 else ''}{'-' if tie else ''}"

    def chord_name(self, degree):
        letter = LETTERS[(self.tonic_index + degree) % 7]
        alt = self.acc[letter]
        name = letter + {1: "#", -1: "b", 0: ""}[alt]
        quality = "m" if degree % 7 in (1, 2, 5) else ""
        return name + quality

    def add_section(self, comment, vocal_bars, ins_bars):
        first = True
        for i in range(0, len(vocal_bars), 4):
            self.groups.append((comment if first else None, vocal_bars[i:i + 4], ins_bars[i:i + 4]))
            first = False

    def text(self, bpm):
        lines = ["X:1", "T:", "M:4/4", "L:1/16", f"Q:1/4={bpm}",
                 'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
                 'V: Ins clef=treble name="Ins Melody" snm="Inst."', f"K:{self.key}"]
        for comment, vocal, ins in self.groups:
            if comment:
                lines.append(f"% {comment}")
            lines += ["V: Vocal", "|".join(vocal) + "|", "V: Ins", "|".join(ins) + "|"]
        return "\n".join(lines) + "\n"


def compose(style, lyrics, seed):
    rng = random.Random(seed)
    active = faults()

    def hit(name):
        return name in active and rng.random() < active[name]

    bpm_match = re.search(r"(\d{2,3})\s*BPM", style, re.I)
    bpm = int(bpm_match.group(1)) if bpm_match else rng.choice([76, 84, 92, 100, 112, 124])
    key = rng.choice(MAJOR_KEYS)
    tonic_index = 4 * 7 + LETTERS.index(key[0])
    if tonic_index - 28 > 1:
        tonic_index -= 7  # tonic between E3 and D4: melodies stay inside a comfortable pop range
    w = Writer(key, tonic_index)
    simple = "simple" in active or rng.random() < 0.6
    sections = parse_lyrics(lyrics)
    if not sections:
        sections = [{"tag": "verse", "lines": ["la la la"]}]
    if "skip_section" in active and len([s for s in sections if s["lines"]]) > 2 and hit("skip_section"):
        vocal_idx = [i for i, s in enumerate(sections) if s["lines"]]
        sections.pop(rng.choice(vocal_idx[1:]))
    if hit("repeat_section"):
        for i, s in enumerate(sections):
            if s["tag"] == "chorus":
                sections.insert(i + 1, dict(s))
                break
    loop_bar = None
    for section in sections:
        tag = section["tag"]
        comment = SECTION_COMMENT.get(tag, "verse")
        prog = PROGRESSIONS[0] if simple else rng.choice(PROGRESSIONS)
        base = {"chorus": 1, "bridge": 1}.get(tag, 0)
        vocal_bars, ins_bars = [], []
        if not section["lines"]:
            sing = hit("vocal_in_instrumental")  # what the real model does: a singer's line anyway
            for b in range(4 if tag != "outro" else 2):
                degree = prog[b % 4]
                if sing:
                    vocal_bars.append(f'"{w.chord_name(degree)}"' + " ".join(w.note(degree + 4 + d, 4) for d in (0, 1, 2, 1)))
                    ins_bars.append("Z" if b % 2 else " ".join(w.note(degree + d, 4) for d in (0, 2, 4, 2)))
                else:
                    vocal_bars.append(f'"{w.chord_name(degree)}"z16')
                    ins_bars.append(" ".join(w.note(degree + d, 4) for d in (0, 2, 4, 2)))
            w.add_section(comment, vocal_bars, ins_bars)
            continue
        degree_now = base + 2
        for line in section["lines"]:
            syl = count_syllables(line)
            n_notes = syl
            if hit("cram"):
                n_notes = max(2, int(syl * 0.55))
            elif hit("melisma"):
                n_notes = int(syl * 1.9) + 2
            durations = [2 if rng.random() < 0.75 else 4 for _ in range(n_notes)]
            durations[-1] = rng.choice([6, 8])
            events, pitches = [], []
            for _ in durations:
                degree_now = max(base - 1, min(base + 6, degree_now + rng.choice([-2, -1, -1, 0, 1, 1, 2])))
                pitches.append(degree_now)
            if tag == "chorus" and hit("leap_end"):
                pitches[-1] = max(pitches) + 6
            events = list(zip(pitches, durations))
            bars, cur, used = [], [], 0
            bar_index = len(vocal_bars)
            for degree, dur in events:
                while dur > 0:
                    if used == 0:
                        cur.append(f'"{w.chord_name(prog[(bar_index + len(bars)) % 4])}"')
                    take = min(dur, 16 - used)
                    parts = split_units(take)
                    for k, part in enumerate(parts):
                        last_piece = (k == len(parts) - 1) and take == dur
                        cur.append(w.note(degree, part, tie=not last_piece))
                    used += take
                    dur -= take
                    if used == 16:
                        bars.append(" ".join(cur))
                        cur, used = [], 0
            if used:
                cur += [f"z{u}" if u != 1 else "z" for u in split_units(16 - used)]
                bars.append(" ".join(cur))
            if len(bars) % 2:
                bars.append(f'"{w.chord_name(prog[(bar_index + len(bars)) % 4])}"z16')
            vocal_bars += bars
            for bi in range(len(bars)):
                if bi == len(bars) - 1 and hit("busy_ins"):
                    ins_bars.append(" ".join(w.note(base + 7 + (k % 5), 1) for k in range(16)))
                else:
                    ins_bars.append("Z")
        if tag == "verse" and hit("loop"):
            untied = [b for b in vocal_bars if not b.endswith("-")]
            loop_bar = loop_bar or (untied[0] if untied else None)
            if loop_bar:
                vocal_bars = [loop_bar] * len(vocal_bars)
        w.add_section(comment, vocal_bars, ins_bars)
    return w.text(bpm)
