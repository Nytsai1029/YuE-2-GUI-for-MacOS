"""Section tags: the official YuE2 vocabulary and every common alias users type.

Official (examples/full-song.json): [Intro] [Verse] [Pre-Chorus] [Chorus] [Interlude]
[Bridge] [Outro], one tag per line, a blank line between sections, instrumental sections
written as an empty tag.
"""
from __future__ import annotations

import re

CANONICAL = ("Intro", "Verse", "Pre-Chorus", "Chorus", "Bridge", "Interlude", "Outro")
INSTRUMENTAL_OK = {"Intro", "Interlude", "Outro"}  # may be empty (no sung lines)
VOCAL_REQUIRED = {"Verse", "Pre-Chorus", "Chorus", "Bridge"}

_ALIASES = {
    "Intro": ["intro", "introduction", "opening", "prelude", "前奏", "开场", "引子", "序"],
    "Verse": ["verse", "v", "主歌", "a段", "a", "rap", "rap verse", "verse rap", "说唱", "主歌部分"],
    "Pre-Chorus": ["pre-chorus", "prechorus", "pre chorus", "pre", "pre-hook", "prehook", "导歌", "预副歌",
                   "副歌前", "前副歌", "b段", "lift", "build", "build up", "buildup"],
    "Chorus": ["chorus", "hook", "refrain", "副歌", "高潮", "c段", "post-chorus", "postchorus", "post chorus",
               "final chorus", "last chorus", "副歌部分"],
    "Bridge": ["bridge", "middle 8", "middle eight", "桥段", "过渡", "桥", "d段", "breakdown"],
    "Interlude": ["interlude", "instrumental", "inst", "solo", "guitar solo", "piano solo", "sax solo", "break",
                  "instrumental break", "drop", "间奏", "过门", "独奏", "器乐", "间奏部分", "musical break"],
    "Outro": ["outro", "ending", "end", "coda", "fade out", "fadeout", "尾奏", "结尾", "尾声", "结束", "outro chorus"],
}
ALIAS = {alias: canon for canon, names in _ALIASES.items() for alias in names}

# Repeat directives users write instead of spelling the section out (A2).
RE_REPEAT_SUFFIX = re.compile(r"\s*(?:[x×*✕]\s*(\d+)|(\d+)\s*[x×*✕]|repeat|重复|\((?:x|×)?\s*(\d+)\s*\))\s*$", re.I)
RE_REPEAT_LINE = re.compile(
    r"^\s*[\(\[（【]?\s*(?:repeat\s+(?:the\s+)?(?P<en>[a-z -]+?)(?:\s*[x×]\s*(?P<n1>\d+))?|"
    r"(?:重复|再唱一遍|再来一遍)\s*(?P<zh1>[一-鿿]+)?|(?P<zh2>[一-鿿]+?)\s*(?:重复|再唱一遍|再来一遍)"
    r"(?:\s*[x×]\s*(?P<n2>\d+))?)\s*[\)\]）】]?\s*$", re.I)
RE_TAG_LINE = re.compile(r"^\s*[\[【]\s*([^\]】]+?)\s*[\]】]\s*(?:[x×*]\s*\d+)?\s*$")


def _key(raw: str) -> str:
    text = raw.strip().lower()
    text = re.sub(r"[：:（(].*$", "", text).strip()          # "Verse 1: rap" -> "verse 1"
    text = re.sub(r"[_]+", " ", text)
    text = re.sub(r"\s*(?:\d+|[一二三四五六七八九十]+|[ivx]+)\s*$", "", text)  # trailing numbering
    text = re.sub(r"^(?:第[一二三四五六七八九十\d]+段?)", "", text)
    return text.strip(" -")


def canonical(raw: str) -> str | None:
    """Map a user tag to the official vocabulary, or None if unknown."""
    base = RE_REPEAT_SUFFIX.sub("", raw).strip()
    key = _key(base)
    if key in ALIAS:
        return ALIAS[key]
    for name in CANONICAL:
        if key == name.lower():
            return name
    # "Verse (Rap)", "Chorus - Final", "Male Verse"
    for alias, canon in sorted(ALIAS.items(), key=lambda kv: -len(kv[0])):
        if len(alias) > 2 and re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", key):
            return canon
    return None


def repeat_count(raw: str) -> int:
    raw = re.sub(r"[\[\]【】]", " ", raw).strip()
    m = RE_REPEAT_SUFFIX.search(raw)
    if not m:
        return 1
    digits = next((g for g in m.groups() if g), None)
    return int(digits) if digits else 2


def parse_tag_line(line: str) -> str | None:
    m = RE_TAG_LINE.match(line)
    return m.group(1).strip() if m else None


def parse_repeat_line(line: str) -> tuple[str, int] | None:
    """'(Repeat Chorus x2)' / '副歌重复' -> ('Chorus', 2)."""
    m = RE_REPEAT_LINE.match(line)
    if not m:
        return None
    name = m.group("en") or m.group("zh1") or m.group("zh2") or "chorus"
    canon = canonical(name) or ("Chorus" if not name else None)
    if canon is None:
        return None
    n = int(m.group("n1") or m.group("n2") or 1)
    return canon, n
