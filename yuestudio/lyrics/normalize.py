"""Sung-text normalization: what the singer receives, one transform at a time.

The user's display text (used for LRC/karaoke) is never modified silently. Instead the
engine receives a normalized copy in the official YuE2 house style, and every line keeps
a mapping back to its display line. Each transform is also exposed individually so the
linter can offer it as a one-click quick-fix on the display text.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

from .text import (
    RE_CJK,
    RE_DIGITS,
    RE_EMOJI,
    RE_URL,
    SYMBOL_WORDS,
    en_number,
    line_language,
    zh_number,
)

RE_PAREN = re.compile(r"[\(（]([^\)）]*)[\)）]")
RE_ASTERISK = re.compile(r"\*([^*]+)\*")
RE_INLINE_BRACKET = re.compile(r"\[([^\]]+)\]|【([^】]+)】")
RE_SPEAKER = re.compile(
    r"^\s*(?:(?:男|女|合|男声|女声|合唱|独唱|领唱|和声|[A-Da-d]|male|female|man|woman|both|all|duet|lead|"
    r"harmony|backing|singer\s*\d*|rapper|feat\.?[^:：]{0,20})\s*[:：])\s*", re.I)
STAGE_WORDS = re.compile(
    r"^(?:x\s*\d+|\d+\s*x|repeat.*|spoken|speaking|whisper(?:ed|ing)?|shout(?:ed|ing)?|scream(?:ed|ing)?|"
    r"instrumental|inst|solo|guitar solo|piano solo|drum.*|beat.*|music|fade.*|echo|ad-?lib.*|laugh(?:s|ing)?|"
    r"sigh|breath|pause|silence|applause|intro|outro|chorus|verse|bridge|hook|interlude|"
    r"旁白|念白|独白|说|低语|耳语|喊|笑|叹气|间奏|独奏|前奏|尾奏|重复.*|合唱|和声|伴唱)$", re.I)
FILLER = re.compile(r"^(?:h+m+|m+|mm+h*|a+h+|o+h+|o+|u+h+|la|na|da|yeah|ye|woah|whoa|嗯|啊|啦|哦|噢|呜|喔|哈|呀|哎|唔|吧)$",
                    re.I)
KEEP_CAPS = {"I", "OK", "O", "A", "TV", "DJ", "MC", "USA", "UK", "LA", "NYC", "CEO", "VIP", "AI", "ID"}
ZH_BREAK = "，、。；：！？…—,;:!?"
ZH_DROP = "“”‘’「」『』《》〈〉（）【】〔〕\"()~～·•*#^_=|\\/<>{}"
DECOR = "~～♪♫♬♩★☆♡♥❤✨✿❀◆◇○●□■△▲▽▼"


@dataclass
class SungLine:
    display_index: int      # editor line index of the user's text
    section: int            # index into the expanded section list
    display: str
    sung: str
    changes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- single transforms
def strip_speaker(text: str) -> str:
    return RE_SPEAKER.sub("", text, count=1)


def strip_stage_directions(text: str) -> str:
    def paren(m):
        inner = m.group(1).strip()
        return " " if STAGE_WORDS.match(inner) or not inner else m.group(0)
    text = RE_PAREN.sub(paren, text)
    text = RE_ASTERISK.sub(" ", text)
    text = RE_INLINE_BRACKET.sub(" ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def unwrap_backing(text: str) -> str:
    """(oh yeah) -> oh yeah : keep backing words sung inline, lose the parentheses."""
    return re.sub(r"\s{2,}", " ", RE_PAREN.sub(lambda m: " " + m.group(1).strip() + " ", text)).strip()


def drop_backing(text: str) -> str:
    return re.sub(r"\s{2,}", " ", RE_PAREN.sub(" ", text)).strip()


def strip_emoji_decor(text: str) -> str:
    text = RE_EMOJI.sub("", text)
    return "".join(ch for ch in text if ch not in DECOR).strip()


def strip_urls(text: str) -> str:
    return re.sub(r"\s{2,}", " ", RE_URL.sub(" ", text)).strip()


def spell_numbers(text: str, lang: str | None = None) -> str:
    lang = lang or line_language(text)

    def number(m):
        token = m.group(0)
        before = text[max(0, m.start() - 1):m.start()]
        after = text[m.end():m.end() + 1]
        zh_context = lang in ("zh", "mixed") and (RE_CJK.match(before or "") or RE_CJK.match(after or "")
                                                   or lang == "zh")
        if zh_context:
            return zh_number(token)
        words = en_number(token)
        pad_l = " " if before and before.isalnum() else ""
        pad_r = " " if after and after.isalnum() else ""
        return pad_l + words + pad_r

    return RE_DIGITS.sub(number, text)


def spell_symbols(text: str, lang: str | None = None) -> str:
    lang = lang or line_language(text)
    out = []
    for ch in text:
        if ch in SYMBOL_WORDS:
            en, zh = SYMBOL_WORDS[ch]
            out.append(zh if lang == "zh" else f" {en} ")
        else:
            out.append(ch)
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


def calm_caps(text: str) -> str:
    """SHOUTED words -> lower case (A15). Short acronyms and 'I' are kept."""
    def word(m):
        w = m.group(0)
        if w in KEEP_CAPS or len(w) <= 3:
            return w
        return w.lower()
    text = re.sub(r"\b[A-Z][A-Z']+\b", word, text)
    return text


def zh_punctuation(text: str) -> str:
    """House style for Chinese lines: no punctuation; phrase breaks become one space."""
    out = []
    for ch in text:
        if ch in ZH_BREAK:
            out.append(" ")
        elif ch in ZH_DROP:
            out.append(" " if ch in "（）()" else "")
        else:
            out.append(ch)
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


def en_punctuation(text: str) -> str:
    text = re.sub(r"[“”\"«»]", "", text)
    text = re.sub(r"(?<![A-Za-z])['’]|['’](?![A-Za-z])", "", text)   # keep don't / rock'n'roll
    text = re.sub(r"[,.;:!?…—–()\[\]{}~～*#_|\\/<>]+", " ", text)
    text = re.sub(r"\s*-\s+|\s+-\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def whitespace(text: str) -> str:
    text = text.replace("　", " ").replace("\t", " ").replace(" ", " ")
    return re.sub(r" {2,}", " ", text).strip()


@functools.lru_cache(maxsize=1)
def _t2s():
    try:
        import opencc

        return opencc.OpenCC("t2s")
    except Exception:
        return None


def to_simplified(text: str) -> str:
    conv = _t2s()
    return conv.convert(text) if conv else text


def apply_lexicon(text: str, lexicon: dict[str, str] | None) -> str:
    if not lexicon:
        return text
    for term in sorted(lexicon, key=len, reverse=True):
        sung = lexicon[term]
        if not term:
            continue
        if re.fullmatch(r"[A-Za-z0-9' -]+", term):
            text = re.sub(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", sung, text, flags=re.I)
        else:
            text = text.replace(term, sung)
    return text


# --------------------------------------------------------------------------- pipeline
@dataclass
class SungOptions:
    backing: str = "unwrap"           # "unwrap" | "drop" | "keep"
    simplified: bool = True
    lexicon: dict[str, str] | None = None


def sing_line(text: str, opts: SungOptions | None = None) -> tuple[str, list[str]]:
    opts = opts or SungOptions()
    changes: list[str] = []

    def step(name, fn, value):
        new = fn(value)
        if new != value:
            changes.append(name)
        return new

    t = step("lexicon", lambda s: apply_lexicon(s, opts.lexicon), text)
    t = step("whitespace", whitespace, t)
    t = step("speaker", strip_speaker, t)
    t = step("url", strip_urls, t)
    t = step("stage", strip_stage_directions, t)
    if opts.backing == "unwrap":
        t = step("backing", unwrap_backing, t)
    elif opts.backing == "drop":
        t = step("backing", drop_backing, t)
    t = step("emoji", strip_emoji_decor, t)
    lang = line_language(t)
    t = step("numbers", lambda s: spell_numbers(s, lang), t)
    t = step("symbols", lambda s: spell_symbols(s, lang), t)
    t = step("caps", calm_caps, t)
    if opts.simplified and lang in ("zh", "mixed"):
        t = step("simplified", to_simplified, t)
    if lang in ("zh", "mixed"):
        t = step("punctuation", zh_punctuation, t)
    else:
        t = step("punctuation", en_punctuation, t)
    t = step("whitespace", whitespace, t)
    return t, changes


def sung_lyrics(doc, opts: SungOptions | None = None) -> tuple[str, list[SungLine]]:
    """Build the exact lyric text sent to YuE2 (official house style) + line mapping."""
    out_lines: list[str] = []
    mapping: list[SungLine] = []
    for si, section in enumerate(doc.expanded()):
        tag = section.tag or "Verse"
        if out_lines:
            out_lines.append("")
        out_lines.append(f"[{tag}]")
        if not section.lines:
            out_lines.append("")  # official style: an instrumental section is an empty tag
            continue
        group = section.lines[0].group
        for line in section.lines:
            sung, changes = sing_line(line.text, opts)
            if not sung:
                continue
            if line.group != group:
                out_lines.append("")
                group = line.group
            out_lines.append(sung)
            mapping.append(SungLine(line.index, si, line.text, sung, changes))
    text = "\n".join(out_lines).strip("\n") + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, mapping


def is_filler_line(text: str) -> float:
    """Fraction of a line made of vocables (hmm, la, oh, 啦, 嗯...)."""
    tokens = re.findall(r"[A-Za-z]+|[一-鿿]", text)
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if FILLER.match(t)) / len(tokens)
