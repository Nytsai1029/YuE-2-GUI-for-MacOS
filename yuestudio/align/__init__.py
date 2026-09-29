"""ASR transcript <-> lyrics alignment: per-line coverage, skipped / repeated / out-of-order
lines (A1, A2, A17) and inserted words (A13).

Chinese is compared as toneless pinyin so homophones the ASR picks don't count as
errors; English as lower-case words. ASR is used for *relative* evidence between takes
of the same lyrics, never as an absolute verdict.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

try:
    from pypinyin import lazy_pinyin
except Exception:  # pragma: no cover
    lazy_pinyin = None


def tokens(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"[㐀-鿿]|[A-Za-z]+(?:'[A-Za-z]+)?", text):
        tok = m.group(0)
        if re.match(r"[㐀-鿿]", tok):
            out.append(lazy_pinyin(tok)[0] if lazy_pinyin else tok)
        else:
            out.append(tok.lower().replace("'", ""))
    return out


def word_tokens(words: list[dict]) -> list[tuple[str, float, float]]:
    out = []
    for w in words:
        toks = tokens(w.get("text", ""))
        if not toks:
            continue
        dur = (w["end"] - w["start"]) / len(toks)
        for i, t in enumerate(toks):
            out.append((t, w["start"] + i * dur, w["start"] + (i + 1) * dur))
    return out


def coverage(lines: list[dict], words: list[dict]) -> dict:
    """lines: sung line occurrences in order [{"line": editor id, "text": sung text}]."""
    lyr, owner = [], []
    for i, ln in enumerate(lines):
        for t in tokens(ln["text"]):
            lyr.append(t)
            owner.append(i)
    heard = word_tokens(words)
    seq = [t for t, _, _ in heard]
    if not lyr:
        return {"available": True, "coverage": 1.0, "lines": [], "skipped": [], "repeated": [], "insertions": 0}
    sm = SequenceMatcher(None, lyr, seq, autojunk=False)
    matched_l = [None] * len(lyr)
    used_h = [False] * len(seq)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            matched_l[a + k] = b + k
            used_h[b + k] = True
    per = []
    for i, ln in enumerate(lines):
        idx = [j for j, o in enumerate(owner) if o == i]
        hits = [matched_l[j] for j in idx if matched_l[j] is not None]
        cov = len(hits) / max(1, len(idx))
        start = heard[hits[0]][1] if hits else None
        end = heard[hits[-1]][2] if hits else None
        per.append({"occurrence": i, "line": ln["line"], "coverage": round(cov, 3), "start": start, "end": end,
                    "tokens": len(idx)})
    skipped = [p["occurrence"] for p in per if p["coverage"] < 0.3 and p["tokens"] >= 3]
    # Unmatched runs of heard tokens that strongly resemble a lyric line = extra repetition.
    repeated, run = [], []
    line_toks = [tokens(ln["text"]) for ln in lines]
    for j, used in enumerate(used_h + [True]):
        if not used and j < len(seq):
            run.append(j)
            continue
        if len(run) >= 4:
            chunk = [seq[k] for k in run]
            best = max(range(len(lines)), key=lambda i: SequenceMatcher(None, line_toks[i], chunk).ratio())
            ratio = SequenceMatcher(None, line_toks[best], chunk).ratio()
            if ratio >= 0.7:
                repeated.append({"line": lines[best]["line"], "start": heard[run[0]][1], "end": heard[run[-1]][2],
                                 "similarity": round(ratio, 2)})
        run = []
    starts = [p["start"] for p in per if p["start"] is not None]
    disorder = sum(1 for a, b in zip(starts, starts[1:]) if b < a - 1.0)
    total = sum(1 for m in matched_l if m is not None) / len(lyr)
    insertions = sum(1 for u in used_h if not u)
    return {"available": True, "coverage": round(total, 3), "lines": per, "skipped": skipped, "repeated": repeated,
            "out_of_order": disorder, "insertions": insertions, "heard_tokens": len(seq)}
