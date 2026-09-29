"""Lyrics <-> score alignment: the lyric-loss predictor (A1/A17) and the singability
fit (A6/A7/A16).

1. Sections: the lyric section sequence is DP-aligned to the ABC section sequence with
   1:1, 2:1 and 1:2 matches plus skips. A skipped *lyric* section is a planned lyric
   loss; a skipped *vocal ABC* section is an extra (usually repeated) section.
2. Lines: inside every matched pair, the vocal notes are segmented into exactly as many
   phrases as there are lyric lines. Candidate boundaries are scored by breath evidence
   (rest length, long final note, barline); segment sizes are matched to syllables.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

from ..abc.score import Note, Score

NAME_GROUP = {"verse": "verse", "pre-chorus": "verse", "chorus": "chorus", "bridge": "bridge",
              "intro": "inst", "interlude": "inst", "outro": "inst", "": "any"}


@dataclass
class LyricUnit:
    index: int              # index into expanded lyric sections
    tag: str
    syllables: list[int]    # per line
    line_ids: list[int]     # editor line index per line (display mapping)

    @property
    def total(self) -> int:
        return sum(self.syllables)

    @property
    def vocal(self) -> bool:
        return bool(self.syllables)


@dataclass
class AbcUnit:
    index: int
    name: str
    notes: list[Note]
    bars: int

    @property
    def vocal(self) -> bool:
        return len(self.notes) > 0


@dataclass
class LineFit:
    line_id: int
    syllables: int
    notes: int
    start: float            # seconds
    end: float
    breath: float           # boundary strength before the next line (0..4)
    note_range: tuple[int, int]

    @property
    def ratio(self) -> float:
        return self.notes / max(1, self.syllables)

    def to_dict(self):
        return {"line": self.line_id, "syllables": self.syllables, "notes": self.notes, "ratio": round(self.ratio, 2),
                "start": round(self.start, 3), "end": round(self.end, 3), "breath": self.breath,
                "note_range": list(self.note_range)}


@dataclass
class SectionMatch:
    lyric: list[int]
    abc: list[int]
    cost: float
    lines: list[LineFit] = field(default_factory=list)

    def to_dict(self):
        return {"lyric": self.lyric, "abc": self.abc, "cost": round(self.cost, 3),
                "lines": [f.to_dict() for f in self.lines]}


@dataclass
class Alignment:
    matches: list[SectionMatch]
    missing_lyric: list[int]      # lyric sections with no ABC counterpart (A1)
    extra_abc: list[int]          # vocal ABC sections with no lyric counterpart (A17)
    lines: list[LineFit]

    def to_dict(self):
        return {"matches": [m.to_dict() for m in self.matches], "missing_lyric": self.missing_lyric,
                "extra_abc": self.extra_abc, "lines": [f.to_dict() for f in self.lines]}


# --------------------------------------------------------------------------- units
def lyric_units(expanded_sections, syllable_fn) -> list[LyricUnit]:
    out = []
    for i, s in enumerate(expanded_sections):
        out.append(LyricUnit(i, s.tag or "Verse", [max(1, syllable_fn(li.text)) for li in s.lines],
                             [li.index for li in s.lines]))
    return out


def abc_units(score: Score) -> list[AbcUnit]:
    return [AbcUnit(sec.index, sec.name, score.section_vocal(sec.index), len(sec.bars)) for sec in score.sections]


# --------------------------------------------------------------------------- section DP
def _ratio_cost(notes: int, syllables: int) -> float:
    if syllables == 0 and notes == 0:
        return 0.0
    if syllables == 0 or notes == 0:
        return 6.0
    r = notes / syllables
    return abs(math.log(r)) * 2.5 + (1.5 if r < 0.7 else 0.0) + (1.5 if r > 1.6 else 0.0)


def _name_cost(tags: list[str], names: list[str]) -> float:
    lg = {NAME_GROUP.get(t.lower(), "verse") for t in tags}
    ag = {NAME_GROUP.get(n, "any") for n in names}
    if "any" in ag:
        return 0.2
    if lg & ag:
        return 0.0
    if lg == {"verse"} and ag <= {"verse", "chorus", "bridge"}:
        return 0.35
    return 0.6


def _pair_cost(ls: list[LyricUnit], as_: list[AbcUnit]) -> float:
    syl = sum(u.total for u in ls)
    notes = sum(len(u.notes) for u in as_)
    lv, av = any(u.vocal for u in ls), any(u.vocal for u in as_)
    if lv != av:
        return 8.0
    if not lv:
        return 0.1 + 0.05 * abs(sum(u.bars for u in as_) - 4)
    merge = 0.8 * (len(ls) - 1 + len(as_) - 1)
    return _ratio_cost(notes, syl) + _name_cost([u.tag for u in ls], [u.name for u in as_]) + merge


def align_sections(lyr: list[LyricUnit], abc: list[AbcUnit]) -> tuple[list[SectionMatch], list[int], list[int]]:
    n, m = len(lyr), len(abc)
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    def skip_lyric(u):
        return 3.5 + 0.05 * u.total if u.vocal else 0.6

    def skip_abc(u):
        return 2.5 if u.vocal else 0.5

    for i in range(n + 1):
        for j in range(m + 1):
            c = cost[i][j]
            if c == INF:
                continue
            steps = []
            if i < n:
                steps.append((i + 1, j, c + skip_lyric(lyr[i]), ("skipL",)))
            if j < m:
                steps.append((i, j + 1, c + skip_abc(abc[j]), ("skipA",)))
            for dl, da in ((1, 1), (2, 1), (1, 2), (3, 1), (1, 3)):
                if i + dl <= n and j + da <= m:
                    pc = _pair_cost(lyr[i:i + dl], abc[j:j + da])
                    steps.append((i + dl, j + da, c + pc, ("match", dl, da, pc)))
            for ni, nj, nc, op in steps:
                if nc < cost[ni][nj] - 1e-9:
                    cost[ni][nj] = nc
                    back[ni][nj] = (i, j, op)
    matches, missing, extra = [], [], []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, op = back[i][j]
        if op[0] == "match":
            matches.append(SectionMatch(list(range(pi, i)), list(range(pj, j)), op[3]))
        elif op[0] == "skipL":
            if lyr[pi].vocal:
                missing.append(pi)
        elif abc[pj].vocal:
            extra.append(pj)
        i, j = pi, pj
    matches.reverse()
    missing.reverse()
    extra.reverse()
    return matches, missing, extra


# --------------------------------------------------------------------------- line segmentation
def _boundary_strength(notes: list[Note], i: int, bar_starts: set[Fraction]) -> float:
    """Evidence of a breath between notes[i-1] and notes[i]."""
    gap = notes[i].onset - notes[i - 1].end
    s = 0.0
    if gap >= 1:
        s = 3.0
    elif gap >= Fraction(1, 2):
        s = 2.2
    elif gap > 0:
        s = 1.4
    if notes[i - 1].dur >= Fraction(3, 2):
        s += 1.0
    elif notes[i - 1].dur >= 1:
        s += 0.5
    if notes[i].onset in bar_starts:
        s += 0.4
    return s


def segment(notes: list[Note], syllables: list[int], bar_starts: set[Fraction]) -> list[tuple[int, int, float]]:
    """Split ``notes`` into len(syllables) contiguous segments -> [(a, b, breath_after)]."""
    n, k = len(notes), len(syllables)
    if k == 0:
        return []
    if n == 0:
        return [(0, 0, 0.0)] * k
    strength = [0.0] + [_boundary_strength(notes, i, bar_starts) for i in range(1, n)] + [4.0]
    INF = float("inf")
    dp = [[INF] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    dp[0][0] = 0.0
    for j in range(1, k + 1):
        syl = syllables[j - 1]
        for b in range(1, n + 1):
            best, arg = INF, 0
            lo = j - 1 if j - 1 <= b - 1 else b - 1
            for a in range(lo, b):
                prev = dp[j - 1][a]
                if prev == INF:
                    continue
                size = b - a
                seg = abs(math.log(size / syl)) * 1.6
                brk = 0.0 if b == n else (1.5 - min(strength[b], 4.0) * 0.55)
                c = prev + seg + brk
                if c < best:
                    best, arg = c, a
            dp[j][b], back[j][b] = best, arg
    if dp[k][n] == INF:  # more lines than notes: give each leftover line nothing
        cuts, b = [], n
        per = max(1, n // k)
        return [(min(i * per, n), min((i + 1) * per, n) if i < k - 1 else n, 0.0) for i in range(k)]
    cuts, b = [], n
    for j in range(k, 0, -1):
        a = back[j][b]
        cuts.append((a, b, strength[b] if b < n else 4.0))
        b = a
    cuts.reverse()
    return cuts


def align(score: Score, lyr: list[LyricUnit]) -> Alignment:
    abc = abc_units(score)
    matches, missing, extra = align_sections(lyr, abc)
    bar_starts = {b.start for b in score.bars}
    all_lines: list[LineFit] = []
    for match in matches:
        syl = [s for li in match.lyric for s in lyr[li].syllables]
        ids = [x for li in match.lyric for x in lyr[li].line_ids]
        notes = [nt for ai in match.abc for nt in abc[ai].notes]
        if not syl:
            continue
        for (a, b, breath), s, line_id in zip(segment(notes, syl, bar_starts), syl, ids):
            chunk = notes[a:b]
            if chunk:
                start, end = score.q2s(chunk[0].onset), score.q2s(chunk[-1].end)
                prange = (min(n.pitch for n in chunk), max(n.pitch for n in chunk))
            else:
                start = end = 0.0
                prange = (0, 0)
            fit = LineFit(line_id, s, len(chunk), start, end, breath, prange)
            match.lines.append(fit)
            all_lines.append(fit)
    return Alignment(matches, missing, extra, all_lines)


def notes_for_lines(score: Score, lyr: list[LyricUnit]) -> list[tuple[int, list[Note]]]:
    """(editor line, vocal notes) for every sung occurrence, in song order (display w: lines)."""
    abc = abc_units(score)
    matches, _, _ = align_sections(lyr, abc)
    bar_starts = {b.start for b in score.bars}
    out: list[tuple[int, list[Note]]] = []
    for match in matches:
        syl = [s for li in match.lyric for s in lyr[li].syllables]
        ids = [x for li in match.lyric for x in lyr[li].line_ids]
        notes = [nt for ai in match.abc for nt in abc[ai].notes]
        for (a, b, _), line_id in zip(segment(notes, syl, bar_starts), ids):
            out.append((line_id, notes[a:b]))
    return out
