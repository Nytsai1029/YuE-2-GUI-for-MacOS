"""Display-only ABC for the browser (abcjs): title, section labels and the user's lyrics
under the notes they are expected to be sung on. Never sent to the engine (the native
dialect forbids w: lines)."""
from __future__ import annotations

import re

from ..analysis import fit as F
from ..lyrics import syllables as S
from ._vendor.abc_tools import TOKEN
from .score import Score

TIE_SKIP = True   # abcjs gives tied continuation notes their own lyric slot; skip them with '*'


def _line_tokens(line: str):
    """Yield ('note'|'cont'|'rest'|'chord'|'bar', text) for one music line."""
    tie_open = False
    for bar in line.rstrip()[:-1].split("|"):
        bar = bar.strip()
        if re.fullmatch(r"Z[2-4]?", bar):
            yield "rest", bar
            yield "bar", "|"
            continue
        pos = 0
        while pos < len(bar):
            if bar[pos].isspace():
                pos += 1
                continue
            m = TOKEN.match(bar, pos)
            if not m:
                break
            pos = m.end()
            if m.group("chord") is not None or m.group("key") is not None:
                continue
            if m.group("note") == "z":
                yield "rest", m.group(0)
                continue
            yield ("cont" if tie_open else "note"), m.group(0)
            tie_open = bool(m.group("tie"))
        yield "bar", "|"


def _assign(units: list[str], n: int) -> list[str]:
    """Spread ``units`` (sung characters/words) over ``n`` notes (w: syntax)."""
    if n == 0:
        return []
    if not units:
        return ["*"] * n
    k = len(units)
    out = []
    if n >= k:
        owner = [min(k - 1, i * k // n) for i in range(n)]
        for i, o in enumerate(owner):
            out.append(_esc(units[o]) if i == 0 or owner[i - 1] != o else "_")
    else:
        for j in range(n):
            a, b = j * k // n, (j + 1) * k // n
            out.append("~".join(_esc(u) for u in units[a:max(b, a + 1)]))
    return out


def _esc(u: str) -> str:
    return re.sub(r"[-_*~\\|]", "", u) or "*"


def build(score: Score, lyric_units: list[F.LyricUnit], sung_by_line: dict[int, list[str]],
          title: str = "", labels: dict[int, str] | None = None) -> str:
    """``sung_by_line``: editor line -> sung units (chars/words), used for every occurrence."""
    occurrences = F.notes_for_lines(score, lyric_units)
    syll_for_note: dict[int, str] = {}
    index = {id(n): i for i, n in enumerate(score.vocal)}
    for line_id, notes in occurrences:
        for note, syl in zip(notes, _assign(sung_by_line.get(line_id, []), len(notes))):
            syll_for_note[index[id(note)]] = syl
    lines = score.text.splitlines()
    out = lines[:8]
    out[1] = f"T:{title}" if title else "T:"
    labels = labels or {}
    note_i = 0
    section_first_group = {sec.groups[0]: sec for sec in score.sections if sec.groups}
    for g in score.groups:
        sec = section_first_group.get(g.index)
        for i in range(g.first_line, g.last_line + 1):
            text = lines[i]
            if i == g.vocal_line:
                if sec is not None:
                    name = labels.get(sec.index) or (sec.name or "").title()
                    if name:
                        text = f'"^{name}"' + text
                out.append(text)
                syls = []
                for kind, _ in _line_tokens(lines[i]):
                    if kind == "note":
                        syls.append(syll_for_note.get(note_i, "*"))
                        note_i += 1
                    elif kind == "cont" and TIE_SKIP:
                        syls.append("*")
                    elif kind == "bar":
                        syls.append("|")
                if any(s not in ("*", "|", "_") for s in syls):
                    out.append("w: " + " ".join(syls))
            elif text.startswith("% "):
                continue
            else:
                out.append(text)
    return "\n".join(out) + "\n"


def sung_units(text: str) -> list[str]:
    return S.units(text)
