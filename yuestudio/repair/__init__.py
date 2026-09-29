"""Plan repairs: fix the score instead of re-rolling.

ops (applied in order, each validated by the vendored parser):
  {"op": "tempo", "bpm": 92}
  {"op": "transpose", "semitones": -2}
  {"op": "reharmonize", "level": "color"|"rich"|"jazz", "sections": [idx...]|null}
  {"op": "set_chords", "bar": 12, "chords": [[0, "Am7"], [2, "D7"]]}
  {"op": "duplicate_section", "section": 3} / {"op": "drop_section", "section": 3}
  {"op": "smooth_endings"}     (A15: tame high-leap line endings and frantic Ins fills)
"""
from __future__ import annotations

from fractions import Fraction
from statistics import median

from ..abc import edit as E
from ..abc.score import parse
from ..analysis.metrics import chord_tones, parse_chord

MAJOR_DEGREES = {0: "", 2: "m", 4: "m", 5: "", 7: "", 9: "m", 11: "dim"}
MINOR_DEGREES = {0: "m", 2: "dim", 3: "", 5: "m", 7: "m", 8: "", 10: ""}


# =========================================================================== melody fit
def _strength(offset: Fraction, bar_len: Fraction) -> float:
    if offset == 0:
        return 1.0
    if offset == bar_len / 2:
        return 0.8
    if offset.denominator == 1:
        return 0.6
    return 0.35


def fit(symbol: str, notes, bar_start: Fraction, bar_len: Fraction) -> tuple[float, bool]:
    c = parse_chord(symbol)
    if not c:
        return -99.0, True
    tones = chord_tones(symbol)
    score, clash = 0.0, False
    for n in notes:
        w = float(n.dur) * _strength(n.onset - bar_start, bar_len)
        pc = n.pitch % 12
        iv = (n.pitch - c["root"]) % 12
        if pc in tones:
            score += w
        elif iv in (2, 9) or (iv == 5 and c["quality"] in ("m", "m7", "sus4", "7sus4")):
            score += 0.1 * w                     # 9th / 13th / 11th colour is fine
        elif any((pc - t) % 12 == 1 for t in tones):
            score -= 2.0 * w                     # half-step above a chord tone: a real clash
            if w >= 0.4:
                clash = True
        else:
            score -= 0.5 * w
    return score, clash


# =========================================================================== reharmonizer
def _name(root_pc: int, quality: str, flats: bool, bass_pc: int | None = None) -> str:
    names = E.FLAT_NAMES if flats else E.SHARP_NAMES
    return names[root_pc % 12] + quality + ("/" + names[bass_pc % 12] if bass_pc is not None else "")


def _extensions(c: dict, degree: int, minor_key: bool) -> list[str]:
    q = c["quality"]
    if q == "":
        if degree == 7:
            return ["7", "7sus4"]
        return ["maj7", "6", "sus2"]
    if q == "m":
        return ["m7", "m6"] if degree in (0, 5, 7) or minor_key else ["m7"]
    if q == "dim":
        return ["m7b5", "dim7"]
    return []


def reharmonize(text: str, level: str = "color", sections: list[int] | None = None) -> tuple[str, list[dict]]:
    score = parse(text)
    tonic, minor_key = E.key_tonic(score.key)
    flats = E.uses_flats(score.key)
    degrees = MINOR_DEGREES if minor_key else MAJOR_DEGREES
    bars = score.bars
    implied = []
    last = None
    for b in bars:
        if b.chords:
            last = b.chords[-1][1]
        implied.append([(o, s) for o, s in b.chords] or ([(Fraction(0), last)] if last else []))
    changes = []
    plan: dict[int, list[tuple[Fraction, str]]] = {}
    half_ok = score.meter[0] in (2, 4) and score.meter[1] == 4
    for i, b in enumerate(bars):
        if sections is not None and b.section not in sections:
            continue
        if not implied[i] or not b.vocal and level == "color" and not b.chords:
            continue
        cur = implied[i]
        new = []
        for k, (off, sym) in enumerate(cur):
            c = parse_chord(sym)
            if not c:
                new.append((off, sym))
                continue
            end = cur[k + 1][0] if k + 1 < len(cur) else b.length
            span = [n for n in b.vocal if b.start + off <= n.onset < b.start + end]
            base, _ = fit(sym, span, b.start, b.length)
            degree = (c["root"] - tonic) % 12
            best, best_score = sym, base
            if c["bass"] is None and degree in degrees:
                for q in _extensions(c, degree, minor_key):
                    cand = _name(c["root"], q, flats)
                    s, clash = fit(cand, span, b.start, b.length)
                    pref = 0.25 if level in ("rich", "jazz") or q in ("7", "m7", "maj7") else 0.0
                    if not clash and s + pref >= best_score - 0.15:
                        best, best_score = cand, s + pref
            new.append((off, best))
        # second-half passing chords (needs a single chord in this bar and a 4/4 or 2/4 meter)
        nxt = implied[i + 1][0][1] if i + 1 < len(bars) and implied[i + 1] else None
        nc = parse_chord(nxt) if nxt else None
        if half_ok and len(new) == 1 and nc and b.vocal is not None:
            half = b.length / 2
            second = [n for n in b.vocal if n.onset >= b.start + half]
            cur_c = parse_chord(new[0][1])
            options = []
            target_deg = (nc["root"] - tonic) % 12
            cur_deg = (cur_c["root"] - tonic) % 12 if cur_c else None
            if cur_c and cur_deg == 0 and target_deg == 9 and not minor_key:
                options.append(_name(tonic + 7, "", flats, bass_pc=tonic + 11))      # I - V/7 - vi walkdown
            if level in ("rich", "jazz") and target_deg in degrees and target_deg != 0 and \
                    degrees[target_deg] != "dim" and nc["root"] != (cur_c or {}).get("root"):
                options.append(_name(nc["root"] + 7, "7", flats))                     # secondary dominant
                if cur_deg == 0 and target_deg == 2:
                    options.append(_name(tonic + 1, "dim7", flats))                   # passing #idim7
            if level in ("rich", "jazz") and cur_deg == 5 and target_deg == 0 and not minor_key:
                options.append(_name(tonic + 5, "m", flats))                          # borrowed iv
            if level == "jazz" and target_deg == 7:
                options.append(_name(tonic + 2, "m7", flats))                         # ii-V
            scored = []
            for opt in options:
                s, clash = fit(opt, second, b.start, b.length)
                if not clash and s >= -0.2:
                    scored.append((s, opt))
            if scored:
                new.append((half, max(scored)[1]))
        if new != cur:
            plan[i] = new
            changes.append({"bar": i, "section": b.section, "before": [s for _, s in cur],
                            "after": [s for _, s in new], "time": score.q2s(b.start)})
    for i, chords in plan.items():
        text = E.set_bar_chords(text, i, chords)
    return text, changes


# =========================================================================== A15 smoother
def smooth_endings(text: str, gender_high: int = 74) -> tuple[str, list[dict]]:
    score = parse(text)
    song = sorted(n.pitch for n in score.vocal)
    if not song:
        return text, []
    p85 = song[int(len(song) * 0.85)]
    targets: dict[int, int] = {}
    index = {id(n): i for i, n in enumerate(score.vocal)}
    changes = []
    chord_at = score.chord_timeline()
    for ph in score.phrases(Fraction(1, 2)):
        pitches = [n.pitch for n in ph.notes]
        if len(pitches) < 3:
            continue
        last = ph.notes[-1]
        med = median(pitches)
        if last.dur >= Fraction(1, 2) and last.pitch == max(pitches) and (
                last.pitch - med >= 7 or (last.pitch - med >= 5 and last.pitch >= p85) or last.pitch > gender_high):
            sym = next((s for t, s in reversed(chord_at) if t <= last.onset), None)
            tones = chord_tones(sym) if sym else {p % 12 for p in pitches}
            options = [p for p in range(int(med) - 5, int(med) + 5) if p % 12 in tones and p < last.pitch]
            if options:
                new = min(options, key=lambda p: (abs(p - (med + 2)), -p))
                targets[index[id(last)]] = new
                changes.append({"kind": "vocal_end", "time": score.q2s(last.onset), "from": last.pitch, "to": new})
    counter = {"i": -1, "tie": False}

    def vocal_fn(events, key, bi, voice):
        out = []
        for ev in events:
            if ev.kind == "note":
                if not counter["tie"]:
                    counter["i"] += 1
                counter["tie"] = ev.tie
                if counter["i"] in targets:
                    ev = E.Ev("note", targets[counter["i"]], ev.units, ev.tie)
            out.append(ev)
        return out

    if targets:
        text = E.map_bars(text, "Vocal", vocal_fn)
    # Frantic instrumental fills right after a line ends: merge runs of very short notes.
    score = parse(text)
    ends = [ph.end for ph in score.phrases(Fraction(1, 2))]
    fast_windows = [(e - Fraction(1, 2), e + 2) for e in ends
                    if sum(1 for n in score.ins if e - Fraction(1, 2) <= n.onset < e + 2 and n.dur <= Fraction(1, 4)) >= 6]
    if fast_windows:
        doc = E.Doc(text)
        unit_q = doc.unit * 4
        starts = {b.index: b.start for b in score.bars}

        def ins_fn(events, key, bi, voice):
            t = starts.get(bi, Fraction(0))
            out, run = [], []

            def flush():
                if run:
                    total = sum(e.units for e in run)
                    parts = E._split_units(total)
                    for j, u in enumerate(parts):
                        out.append(E.Ev("note", run[0].pitch, u, tie=j < len(parts) - 1 or run[-1].tie))
                    run.clear()
            for ev in events:
                if ev.kind == "note":
                    in_window = any(a <= t < b for a, b in fast_windows)
                    if in_window and ev.units * unit_q <= Fraction(1, 4) and not ev.tie:
                        run.append(ev)
                        t += ev.units * unit_q
                        continue
                    flush()
                    t += ev.units * unit_q
                elif ev.kind == "rest":
                    flush()
                    t += ev.units * unit_q
                else:
                    flush()
                out.append(ev)
            flush()
            return out

        before = len(score.ins)
        text = E.map_bars(text, "Ins", ins_fn)
        after = len(parse(text).ins)
        if after < before:
            changes.append({"kind": "ins_fill", "windows": len(fast_windows), "notes_removed": before - after})
    return text, changes


# =========================================================================== dispatcher
def chord_diff(before: str, after: str) -> list[dict]:
    a, b = parse(before), parse(after)
    out = []
    for i, (x, y) in enumerate(zip(a.bars, b.bars)):
        ca, cb = [s for _, s in x.chords], [s for _, s in y.chords]
        if ca != cb:
            out.append({"bar": i, "section": y.section, "before": ca, "after": cb})
    return out


def apply_ops(abc: str, ops: list[dict], key_hint: str | None = None) -> dict:
    text = abc
    applied = []
    try:
        for op in ops:
            kind = op.get("op")
            if kind == "tempo":
                text = E.set_tempo(text, int(op["bpm"]))
                applied.append({"op": kind, "bpm": int(op["bpm"])})
            elif kind == "transpose":
                semis = int(op["semitones"])
                text = E.transpose(text, semis)
                applied.append({"op": kind, "semitones": semis})
            elif kind == "reharmonize":
                text, changes = reharmonize(text, op.get("level", "color"), op.get("sections"))
                applied.append({"op": kind, "level": op.get("level", "color"), "changes": changes})
            elif kind == "set_chords":
                chords = [(Fraction(str(o)), s) for o, s in op["chords"]]
                text = E.set_bar_chords(text, int(op["bar"]), chords)
                applied.append({"op": kind, "bar": op["bar"], "chords": op["chords"]})
            elif kind == "duplicate_section":
                text = E.duplicate_section(text, int(op["section"]))
                applied.append({"op": kind, "section": op["section"]})
            elif kind == "drop_section":
                text = E.drop_section(text, int(op["section"]))
                applied.append({"op": kind, "section": op["section"]})
            elif kind == "smooth_endings":
                text, changes = smooth_endings(text, int(op.get("high", 74)))
                applied.append({"op": kind, "changes": changes})
            else:
                raise E.EditError(f"unknown op {kind!r}")
    except (E.EditError, ValueError, KeyError) as error:
        return {"ok": False, "error": str(error), "applied": applied}
    diff = None
    try:
        diff = chord_diff(abc, text)
    except Exception:
        pass
    return {"ok": True, "abc": text, "applied": applied, "diff": diff}

