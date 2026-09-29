"""Text-level edits of native YuE2 ABC that keep the dialect valid.

Bars are re-emitted from *sounding* pitches, so accidentals, key changes and ties stay
exactly right for the engine's parser (the same rules as abc_tools.parse: per-bar local
accidentals propagate by letter across octaves; unmarked tied continuations keep pitch).
Every public function validates its output with the vendored parser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from ._vendor import abc_tools as T

LETTERS = "CDEFGAB"
NATURAL = T.NATURAL
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
MAJOR_KEYS = ["Cb", "Gb", "Db", "Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#"]
MINOR_KEYS = ["Abm", "Ebm", "Bbm", "Fm", "Cm", "Gm", "Dm", "Am", "Em", "Bm", "F#m", "C#m", "G#m", "D#m", "A#m"]


class EditError(ValueError):
    pass


@dataclass
class Ev:
    kind: str                 # note | rest | chord | key
    pitch: int = 0
    units: int = 0
    tie: bool = False
    text: str = ""            # chord symbol or key name


def pc_of(name: str) -> int:
    return (NATURAL[name[0]] + name.count("#") - name.count("b")) % 12


def key_tonic(key: str) -> tuple[int, bool]:
    minor = key.endswith("m")
    return pc_of(key[:-1] if minor else key), minor


def key_name(tonic: int, minor: bool) -> str:
    names = MINOR_KEYS if minor else MAJOR_KEYS
    options = [k for k in names if key_tonic(k)[0] == tonic % 12]
    return min(options, key=lambda k: abs(T.KEYS[k]))


def uses_flats(key: str) -> bool:
    return T.KEYS[key] < 0 or key in ("F", "Dm")


# --------------------------------------------------------------------------- bar parsing
def parse_bar(body: str, key: str, pending: tuple | None) -> tuple[list[Ev], str, tuple | None]:
    """-> (events, key after bar, pending tie (pitch, written) for the next bar)."""
    events: list[Ev] = []
    local: dict[str, int] = {}
    cursor = 0
    while cursor < len(body):
        if body[cursor].isspace():
            cursor += 1
            continue
        m = T.TOKEN.match(body, cursor)
        if m is None:
            raise EditError(f"unsupported token at {body[cursor:cursor + 16]!r}")
        cursor = m.end()
        if m.group("chord") is not None:
            events.append(Ev("chord", text=m.group("chord")))
            continue
        if m.group("key") is not None:
            key = m.group("key")
            local = {}
            events.append(Ev("key", text=key))
            continue
        note, acc, octave, tie = m.group("note", "acc", "oct", "tie")
        units = int(m.group("duration") or "1")
        if note == "z":
            events.append(Ev("rest", units=units))
            pending = None
            continue
        letter = note.upper()
        written = 60 + NATURAL[letter] + (12 if note.islower() else 0) + 12 * (octave.count("'") - octave.count(","))
        alteration = local.get(letter, T.key_accidentals(key)[letter])
        if acc:
            alteration = {"=": 0, "_": -1, "__": -2, "^": 1, "^^": 2}[acc]
            local[letter] = alteration
        pitch = written + alteration
        if pending is not None and not acc and written == pending[1]:
            pitch = pending[0]
        events.append(Ev("note", pitch=pitch, units=units, tie=bool(tie)))
        pending = (pitch, written) if tie else None
    return events, key, pending


def _spell(pitch: int, key: str) -> tuple[str, int]:
    """Choose letter + alteration for a sounding pitch in ``key``."""
    pc = pitch % 12
    sig = T.key_accidentals(key)
    for letter in LETTERS:
        if (NATURAL[letter] + sig[letter]) % 12 == pc:
            return letter, sig[letter]
    name = (FLAT_NAMES if uses_flats(key) else SHARP_NAMES)[pc]
    return name[0], name.count("#") - name.count("b")


def _note_text(pitch: int, letter: str, alteration: int, explicit: bool) -> str:
    base = pitch - alteration
    octave = (base - NATURAL[letter]) // 12 - 5
    if octave >= 1:
        text = letter.lower() + "'" * (octave - 1)
    else:
        text = letter + "," * (-octave)
    if explicit:
        text = {0: "=", 1: "^", -1: "_", 2: "^^", -2: "__"}[alteration] + text
    return text


def emit_bar(events: list[Ev], key: str) -> str:
    out: list[str] = []
    local: dict[str, int] = {}
    for ev in events:
        if ev.kind == "chord":
            out.append(f'"{ev.text}"')
        elif ev.kind == "key":
            key = ev.text
            local = {}
            out.append(f"[K:{key}]")
        elif ev.kind == "rest":
            out.append("z" + (str(ev.units) if ev.units != 1 else ""))
        else:
            letter, alteration = _spell(ev.pitch, key)
            current = local.get(letter, T.key_accidentals(key)[letter])
            explicit = current != alteration
            if explicit:
                local[letter] = alteration
            out.append(_note_text(ev.pitch, letter, alteration, explicit) + (str(ev.units) if ev.units != 1 else "")
                       + ("-" if ev.tie else ""))
    text = ""
    for i, tok in enumerate(out):  # chords glue to the next token, notes separated by spaces
        text += tok if (i == 0 or out[i - 1].startswith('"')) else " " + tok
    return text


# --------------------------------------------------------------------------- document model
@dataclass
class Line:
    index: int
    voice: str
    bars: list[str]


class Doc:
    """Header + lines; music lines are split into bars (Z rests expanded)."""

    def __init__(self, text: str):
        T.parse(text)  # must start valid
        self.lines = text.splitlines()
        self.unit = Fraction(1, int(re.fullmatch(r"L:1/(\d+)", self.lines[3]).group(1)))
        self.meter = T.meter_value(self.lines[2][2:])
        self.music: list[Line] = []
        voice = None
        for i, line in enumerate(self.lines[8:], start=8):
            if line in ("V: Vocal", "V: Ins"):
                voice = line[3:]
            elif voice and line.endswith("|") and not line.startswith(("%", "M:", "K:")):
                bars = []
                for bar in line[:-1].split("|"):
                    bar = bar.strip()
                    z = re.fullmatch(r"Z([2-4])?", bar)
                    bars += ["Z"] * int(z.group(1) or "1") if z else [bar]
                self.music.append(Line(i, voice, bars))
                voice = None

    def bar_units(self, meter=None) -> int:
        n, d = meter or self.meter
        return int(Fraction(n, d) / self.unit)

    def text(self) -> str:
        lines = list(self.lines)
        for ml in self.music:
            lines[ml.index] = "|".join(ml.bars) + "|"
        return "\n".join(lines) + "\n"

    def voice_lines(self, voice: str) -> list[Line]:
        return [m for m in self.music if m.voice == voice]

    def key_timeline(self) -> dict[int, str]:
        """Key in effect at the start of each music line (header, group K: fields)."""
        key = self.lines[7][2:]
        out = {}
        for i, line in enumerate(self.lines):
            if i >= 8 and line.startswith("K:"):
                key = line[2:]
            if any(m.index == i for m in self.music):
                out[i] = key
        return out


def rest_bar(units: int) -> str:
    parts, left = [], units
    for size in sorted(T.DURATIONS, reverse=True):
        while left >= size:
            parts.append("z" + (str(size) if size != 1 else ""))
            left -= size
    return " ".join(parts)


def map_bars(text: str, voice: str | None, fn) -> str:
    """Apply ``fn(events, key, bar_index, voice) -> events`` to every bar; keeps ties/keys consistent."""
    doc = Doc(text)
    keys = doc.key_timeline()
    for v in ("Vocal", "Ins"):
        if voice not in (None, v):
            continue
        pending = None
        bar_index = 0
        key_state = doc.lines[7][2:]
        for ml in doc.voice_lines(v):
            key_state = keys.get(ml.index, key_state)
            new_bars = []
            for bar in ml.bars:
                if bar == "Z":
                    events, after = [Ev("rest", units=doc.bar_units())], key_state
                    pending = None
                    full_rest = True
                else:
                    events, after, pending = parse_bar(bar, key_state, pending)
                    full_rest = False
                new_events = fn(events, key_state, bar_index, v)
                if full_rest and new_events == events:
                    new_bars.append("Z")
                else:
                    new_bars.append(emit_bar(new_events, key_state))
                key_state = after
                bar_index += 1
            ml.bars = new_bars
    return doc.text()


# --------------------------------------------------------------------------- public edits
def set_tempo(text: str, bpm: int) -> str:
    lines = text.splitlines()
    lines[4] = f"Q:1/4={int(bpm)}"
    out = "\n".join(lines) + "\n"
    check = T.compare(T.parse(text), T.parse(out), allow_tempo_change=True)
    if not check["match"]:
        raise EditError(check["differences"])
    return out


def transpose_chord(symbol: str, semis: int, flats: bool) -> str:
    m = re.fullmatch(r"([A-G](?:bb|##|b|#)?)(.*?)(?:/([A-G](?:bb|##|b|#)?))?", symbol)
    if not m:
        return symbol
    names = FLAT_NAMES if flats else SHARP_NAMES
    root = names[(pc_of(m.group(1)) + semis) % 12]
    bass = "/" + names[(pc_of(m.group(3)) + semis) % 12] if m.group(3) else ""
    return root + m.group(2) + bass


def transpose(text: str, semis: int) -> str:
    if semis == 0:
        return text
    before = T.parse(text)

    def new_key(k):
        tonic, minor = key_tonic(k)
        return key_name(tonic + semis, minor)

    out_doc = Doc(text)
    old_keys = out_doc.key_timeline()          # keys as written in the source, per music line
    header_key = out_doc.lines[7][2:]
    for i, line in enumerate(out_doc.lines):  # header + group K: fields get the new key names
        if i == 7 or (i > 7 and line.startswith("K:")):
            out_doc.lines[i] = "K:" + new_key(line[2:])
    for v in ("Vocal", "Ins"):
        pending = None
        key_state = header_key
        for ml in out_doc.voice_lines(v):
            key_state = old_keys.get(ml.index, key_state)
            new_bars = []
            for bar in ml.bars:
                if bar == "Z":
                    new_bars.append("Z")
                    pending = None
                    continue
                events, after, pending = parse_bar(bar, key_state, pending)
                shifted = []
                for ev in events:
                    if ev.kind == "note":
                        shifted.append(Ev("note", ev.pitch + semis, ev.units, ev.tie))
                    elif ev.kind == "chord":
                        shifted.append(Ev("chord", text=transpose_chord(ev.text, semis, uses_flats(new_key(key_state)))))
                    elif ev.kind == "key":
                        shifted.append(Ev("key", text=new_key(ev.text)))
                    else:
                        shifted.append(ev)
                new_bars.append(emit_bar(shifted, new_key(key_state)))
                key_state = after
            ml.bars = new_bars
    out = out_doc.text()
    after = T.parse(out)
    for name in ("Vocal", "Ins"):
        a, b = before.voices[name].notes, after.voices[name].notes
        if len(a) != len(b) or any(x[0] != y[0] or x[2] != y[2] or x[1] + semis != y[1] for x, y in zip(a, b)):
            raise EditError(f"transposition changed the {name} rhythm")
    return out


def set_bar_chords(text: str, bar_index: int, chords: list[tuple[Fraction, str]]) -> str:
    """Replace the chords of one bar (offsets in quarters from the bar start). Notes that
    straddle a new chord position are split into tied parts (sounding notes unchanged)."""
    doc = Doc(text)
    unit_q = doc.unit * 4
    for sym in [c for _, c in chords]:
        if T.CHORD.fullmatch(sym) is None:
            raise EditError(f"unsupported chord {sym!r}")

    def fn(events, key, bi, voice):
        if bi != bar_index or voice != "Vocal":
            return events
        body = [e for e in events if e.kind != "chord"]
        wanted = sorted(chords, key=lambda c: c[0])
        out, t = [], Fraction(0)
        queue = list(wanted)
        for ev in body:
            if ev.kind == "key":
                out.append(ev)
                continue
            dur = ev.units * unit_q
            start, end = t, t + dur
            while queue and queue[0][0] <= start:
                out.append(Ev("chord", text=queue.pop(0)[1]))
            cuts = [c for c in queue if start < c[0] < end]
            pieces, cursor = [], start
            for c in cuts:
                pieces.append((cursor, c[0], c[1]))
                cursor = c[0]
            pieces.append((cursor, end, None))
            for k, (a, b, _sym) in enumerate(pieces):
                units = int((b - a) / unit_q)
                parts = _split_units(units)
                for j, u in enumerate(parts):
                    last_part = k == len(pieces) - 1 and j == len(parts) - 1
                    if ev.kind == "note":
                        out.append(Ev("note", ev.pitch, u, tie=ev.tie if last_part else True))
                    else:
                        out.append(Ev("rest", units=u))
                if k < len(pieces) - 1:
                    out.append(Ev("chord", text=queue.pop(0)[1]))
            t = end
        return out

    out = map_bars(text, "Vocal", fn)
    check = T.compare(T.parse(text), T.parse(out))
    if not check["match"]:
        raise EditError(check["differences"])
    return out


def _split_units(units: int) -> list[int]:
    parts, left = [], units
    for size in sorted(T.DURATIONS, reverse=True):
        while left >= size:
            parts.append(size)
            left -= size
    if left:
        raise EditError(f"cannot express {units} units")
    return parts


def section_line_range(text: str, section_index: int) -> tuple[int, int]:
    from .score import parse

    score = parse(text)
    sec = score.sections[section_index]
    first = score.groups[sec.groups[0]]
    last = score.groups[sec.groups[-1]]
    return first.first_line, last.last_line


def _crosses_tie(text: str, a: int, b: int) -> bool:
    lines = text.splitlines()
    music = [i for i in range(a, b + 1) if lines[i].endswith("|") and not lines[i].startswith(("%", "V:"))]
    if any(lines[i].rstrip("|").rstrip().endswith("-") for i in music):
        return True
    prev = [i for i in range(8, a) if lines[i].endswith("|") and not lines[i].startswith(("%", "V:"))]
    return any(lines[i].rstrip("|").rstrip().endswith("-") for i in prev[-2:])


def duplicate_section(text: str, section_index: int) -> str:
    a, b = section_line_range(text, section_index)
    if _crosses_tie(text, a, b):
        raise EditError("a tie crosses this section boundary")
    lines = text.splitlines()
    block = lines[a:b + 1]
    out = "\n".join(lines[:b + 1] + block + lines[b + 1:]) + "\n"
    T.parse(out)
    return out


def drop_section(text: str, section_index: int) -> str:
    a, b = section_line_range(text, section_index)
    lines = text.splitlines()
    if any(line.startswith(("K:", "M:")) for line in lines[a:b + 1]) or _crosses_tie(text, a, b):
        raise EditError("this section changes key/meter or is tied to its neighbour")
    out = "\n".join(lines[:a] + lines[b + 1:]) + "\n"
    T.parse(out)
    return out
