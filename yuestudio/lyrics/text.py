"""Character classes, language detection and number spelling for sung text."""
from __future__ import annotations

import re
import unicodedata

CJK = r"㐀-䶿一-鿿豈-﫿"
RE_CJK = re.compile(f"[{CJK}]")
RE_LATIN_WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
RE_KANA = re.compile(r"[぀-ヿ]")
RE_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
RE_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
RE_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")
RE_URL = re.compile(r"(https?://\S+|www\.\S+|\S+@\S+\.\w+)", re.I)
# Emoji and pictographs, dingbats, misc symbols, music notes, hearts, stars.
RE_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF⭐⭕❤♥♡"
    "♪-♯★☆️‍]")

ZH_PUNCT = "，。、；：！？…—～·“”‘’「」『』《》〈〉（）【】〔〕﹏,.;:!?\"()"
ZH_DIGITS = "零一二三四五六七八九"


def cjk_count(text: str) -> int:
    return len(RE_CJK.findall(text))


def latin_words(text: str) -> list[str]:
    return RE_LATIN_WORD.findall(text)


def line_language(text: str) -> str:
    """'zh', 'en', 'mixed', 'ja', 'ko', 'other' or '' for empty."""
    zh = cjk_count(text)
    en = len(latin_words(text))
    if RE_KANA.search(text):
        return "ja"
    if RE_HANGUL.search(text):
        return "ko"
    if RE_CYRILLIC.search(text):
        return "other"
    if zh and en:
        return "mixed"
    if zh:
        return "zh"
    if en:
        return "en"
    stripped = "".join(c for c in text if unicodedata.category(c)[0] == "L")
    return "other" if stripped else ""


def full_to_half(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E and not ("０" <= ch <= "９" and False):
            half = chr(code - 0xFEE0)
            # keep full-width punctuation that Chinese lint handles separately
            out.append(half if half.isalnum() else ch)
        else:
            out.append(ch)
    return "".join(out)


# --------------------------------------------------------------------------- Chinese numbers
def zh_int(n: int) -> str:
    if n == 0:
        return "零"
    if n < 0:
        return "负" + zh_int(-n)
    units = ["", "十", "百", "千"]
    big = ["", "万", "亿", "兆"]

    def four(x):
        s, zero = "", False
        for i in range(3, -1, -1):
            d = (x // 10**i) % 10
            if d == 0:
                zero = bool(s)
            else:
                if zero:
                    s += "零"
                    zero = False
                s += ZH_DIGITS[d] + units[i]
        return s

    parts, i = [], 0
    while n:
        n, chunk = divmod(n, 10000)
        if chunk:
            text = four(chunk) + big[i]
            if parts and chunk < 1000:
                text += "零" if not parts[0].startswith("零") else ""
            parts.insert(0, text)
        i += 1
    out = "".join(parts).rstrip("零")
    if out.startswith("一十"):
        out = out[1:]
    return out


def zh_number(token: str) -> str:
    """Spell a digit string for singing in Chinese. 4-digit years are read digit by digit."""
    if "." in token:
        a, b = token.split(".", 1)
        return zh_int(int(a)) + "点" + "".join(ZH_DIGITS[int(d)] for d in b)
    token = token.replace(",", "")
    if len(token) == 4 and token[0] in "12":
        return "".join(ZH_DIGITS[int(d)] for d in token)
    if len(token) > 1 and token.startswith("0"):
        return "".join(ZH_DIGITS[int(d)] for d in token)
    return zh_int(int(token))


# --------------------------------------------------------------------------- English numbers
_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
        "sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def en_int(n: int) -> str:
    if n < 0:
        return "minus " + en_int(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + ("-" + _ONES[o] if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + " hundred" + (" " + en_int(r) if r else "")
    for value, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= value:
            q, r = divmod(n, value)
            return en_int(q) + " " + name + (" " + en_int(r) if r else "")
    return str(n)


def en_number(token: str) -> str:
    if "." in token:
        a, b = token.split(".", 1)
        return en_int(int(a)) + " point " + " ".join(_ONES[int(d)] for d in b)
    token = token.replace(",", "")
    n = int(token)
    if len(token) == 4 and 1100 <= n <= 2099 and n % 100 != 0 or n in (1900, 1800):
        hi, lo = divmod(n, 100)
        if lo == 0:
            return en_int(hi) + " hundred"
        return en_int(hi) + " " + (("oh " + en_int(lo)) if lo < 10 else en_int(lo))
    if len(token) == 4 and 2000 <= n <= 2009:
        return en_int(n)
    return en_int(n)


SYMBOL_WORDS = {
    "&": ("and", "和"), "@": ("at", "在"), "%": ("percent", "百分之"), "+": ("plus", "加"),
    "=": ("equals", "等于"), "$": ("dollars", "块钱"), "#": ("number", "号"), "°": ("degrees", "度"),
    "℃": ("degrees", "度"), "×": ("times", "乘"),
}
