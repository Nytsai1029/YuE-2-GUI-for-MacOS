"""Syllable counting: one per Han character, CMUdict (if installed) or heuristics for English."""
from __future__ import annotations

import functools
import re

from .text import RE_CJK, RE_LATIN_WORD

_VOWELS = re.compile(r"[aeiouy]+")


@functools.lru_cache(maxsize=1)
def _cmu():
    try:  # optional: `pip install cmudict`
        import cmudict

        return cmudict.dict()
    except Exception:
        return None


def english_word(word: str) -> int:
    w = word.lower().strip("'’-")
    if not w:
        return 0
    cmu = _cmu()
    if cmu is not None and w in cmu:
        return max(1, sum(ch[-1].isdigit() for ch in cmu[w][0]))
    if "-" in w:
        return sum(english_word(p) for p in w.split("-"))
    w = re.sub(r"['’]", "", w)
    groups = _VOWELS.findall(w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1  # silent e: "love", "time"
    if w.endswith("le") and len(w) > 2 and w[-3] not in "aeiouy":
        pass  # "little", "table": the -le is its own syllable already counted
    if w.endswith("ed") and not w.endswith(("ted", "ded")) and n > 1:
        n -= 1  # "walked"
    if w.endswith("es") and not w.endswith(("ses", "zes", "ches", "shes", "ges", "ces", "xes")) and n > 1:
        n -= 1  # "hopes"
    # Vowel hiatus ("piano", "video", "radio") but not the glides in "nation", "special", "region".
    for _ in re.finditer(r"(?<![tscxg])i[ao]|eo", w):
        if len(w) > 4:
            n += 1
    return max(1, n)


def count(text: str) -> int:
    return len(RE_CJK.findall(text)) + sum(english_word(w) for w in RE_LATIN_WORD.findall(text))


def units(text: str) -> list[str]:
    """Sung units in order: each Han character, each English word (for alignment)."""
    out = []
    for m in re.finditer(r"[㐀-鿿豈-﫿]|[A-Za-z]+(?:['’-][A-Za-z]+)*", text):
        out.append(m.group(0))
    return out
