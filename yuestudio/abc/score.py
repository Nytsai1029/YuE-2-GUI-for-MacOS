"""A typed view of a YuE2 native ABC score.

Notes, bars, chords and keys come from the vendored mlx-Yue ``abc_tools.parse`` (the
authoritative dialect implementation). On top we add what the harness needs: text
groups with line numbers, sections from ``% name`` comments, per-bar chords and
rest-delimited vocal phrases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

from ._vendor import abc_tools as T

AbcError = T.AbcError
NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


@dataclass
class Note:
    onset: Fraction          # quarters from song start
    pitch: int               # MIDI
    dur: Fraction            # quarters (ties merged)
    bar: int = 0
    section: int = 0

    @property
    def end(self) -> Fraction:
        return self.onset + self.dur


@dataclass
class Bar:
    index: int
    start: Fraction
    length: Fraction
    group: int
    section: int
    chords: list[tuple[Fraction, str]] = field(default_factory=list)   # (offset in bar, symbol)
    vocal: list[Note] = field(default_factory=list)
    ins: list[Note] = field(default_factory=list)


@dataclass
class Group:
    index: int
    comments: list[str]
    first_line: int          # first text line of the group (its first comment or "V: Vocal")
    vocal_line: int
    ins_line: int
    last_line: int
    bars: list[int] = field(default_factory=list)


@dataclass
class Section:
    index: int
    name: str                # comment name, e.g. "verse" ("" if none)
    groups: list[int] = field(default_factory=list)
    bars: list[int] = field(default_factory=list)
    start: Fraction = Fraction(0)
    end: Fraction = Fraction(0)

    @property
    def vocal_notes(self) -> int:
        return 0


@dataclass
class Phrase:
    index: int
    section: int
    notes: list[Note]

    @property
    def start(self) -> Fraction:
        return self.notes[0].onset

    @property
    def end(self) -> Fraction:
        return self.notes[-1].end


@dataclass
class Score:
    text: str
    bpm: int
    unit: Fraction
    key: str
    meter: tuple[int, int]
    vocal: list[Note]
    ins: list[Note]
    bars: list[Bar]
    groups: list[Group]
    sections: list[Section]
    keys: list[tuple[Fraction, str]]

    @property
    def quarters(self) -> Fraction:
        return self.bars[-1].start + self.bars[-1].length if self.bars else Fraction(0)

    @property
    def seconds(self) -> float:
        return float(self.quarters) * 60.0 / self.bpm

    def q2s(self, q) -> float:
        return float(q) * 60.0 / self.bpm

    def section_vocal(self, si: int) -> list[Note]:
        return [n for n in self.vocal if n.section == si]

    def phrases(self, gap: Fraction = Fraction(1)) -> list[Phrase]:
        """Vocal phrases: split at rests >= ``gap`` quarters and at section boundaries."""
        out: list[Phrase] = []
        cur: list[Note] = []
        for n in self.vocal:
            if cur and (n.onset - cur[-1].end >= gap or n.section != cur[-1].section):
                out.append(Phrase(len(out), cur[0].section, cur))
                cur = []
            cur.append(n)
        if cur:
            out.append(Phrase(len(out), cur[0].section, cur))
        return out

    def chord_timeline(self) -> list[tuple[Fraction, str]]:
        return [(b.start + off, sym) for b in self.bars for off, sym in b.chords]


def _group_scan(text: str) -> list[Group]:
    lines = text.splitlines()
    groups: list[Group] = []
    pending: list[str] = []
    first = None
    i = 8
    while i < len(lines):
        line = lines[i]
        if line.startswith("% "):
            if first is None:
                first = i
            pending.append(line[2:].strip())
            i += 1
            continue
        if line == "V: Vocal":
            start = first if first is not None else i
            j = i + 1
            while j < len(lines) and lines[j].startswith(("M:", "K:")):
                j += 1
            vocal_line = j
            k = j + 1
            if k >= len(lines) or lines[k] != "V: Ins":
                raise T.AbcError(f"line {k + 1}: expected V: Ins")
            k += 1
            while k < len(lines) and lines[k].startswith(("M:", "K:")):
                k += 1
            groups.append(Group(len(groups), pending, start, vocal_line, k, k))
            pending, first = [], None
            i = k + 1
            continue
        i += 1
    return groups


def _bar_count(music_line: str) -> int:
    n = 0
    for bar in music_line.rstrip()[:-1].split("|"):
        bar = bar.strip()
        m = re.fullmatch(r"Z([2-4])?", bar)
        n += int(m.group(1) or "1") if m else 1
    return n


def parse(text: str) -> Score:
    raw = T.parse(text)
    lines = text.splitlines()
    groups = _group_scan(text)
    vocal_v, ins_v = raw.voices["Vocal"], raw.voices["Ins"]
    # bars -> groups -> sections
    bars: list[Bar] = []
    sections: list[Section] = []
    for g in groups:
        if g.comments or not sections:
            sections.append(Section(len(sections), g.comments[-1].lower() if g.comments else ""))
        sec = sections[-1]
        sec.groups.append(g.index)
        count = _bar_count(lines[g.vocal_line])
        for _ in range(count):
            bi = len(bars)
            start, length, _meter = vocal_v.bars[bi]
            bars.append(Bar(bi, start, length, g.index, sec.index))
            g.bars.append(bi)
            sec.bars.append(bi)
    for sec in sections:
        sec.start = bars[sec.bars[0]].start
        sec.end = bars[sec.bars[-1]].start + bars[sec.bars[-1]].length
    starts = [b.start for b in bars]

    def bar_of(t: Fraction) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def notes(voice, attr):
        out = []
        for onset, pitch, dur in voice.notes:
            bi = bar_of(onset)
            n = Note(onset, pitch, dur, bi, bars[bi].section)
            getattr(bars[bi], attr).append(n)
            out.append(n)
        return out

    vocal = notes(vocal_v, "vocal")
    ins = notes(ins_v, "ins")
    for t, sym in vocal_v.chords:
        b = bars[bar_of(t)]
        b.chords.append((t - b.start, sym))
    return Score(text=text, bpm=raw.bpm, unit=raw.unit, key=lines[7][2:], meter=T.meter_value(lines[2][2:]),
                 vocal=vocal, ins=ins, bars=bars, groups=groups, sections=sections, keys=vocal_v.keys)


def try_parse(text: str) -> tuple[Score | None, str | None]:
    try:
        return parse(text), None
    except (T.AbcError, IndexError, ValueError) as error:
        return None, str(error)


def pitch_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"
