"""Style builder: structured fields -> the style string YuE2 expects, plus style lint.

Official convention (examples/quickstart.json):
  "English, warm piano pop, expressive female voice, acoustic piano, rounded bass and
   light drums, lyrical memorable melody, unhurried phrasing, 88 BPM"
i.e. language, genre, vocal, instruments, melody/phrasing descriptors, tempo.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..rules import rule as register
from ..rules import run

VOCAB = json.loads((Path(__file__).parent / "vocab.json").read_text(encoding="utf-8"))

HARMONY = {
    "keep": "",
    "color": "lush seventh chords",
    "rich": "rich chord progressions with borrowed chords",
    "jazz": "jazzy extended harmony",
}
DELIVERY_DEFAULT = "controlled delivery"


@dataclass
class StyleFields:
    language: str = "auto"                  # auto | Chinese | English | Chinese and English
    genres: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    gender: str = "female"                  # female | male | duet | choir | none
    timbre: list[str] = field(default_factory=list)
    delivery: str = "controlled"
    instruments: list[str] = field(default_factory=list)
    production: list[str] = field(default_factory=list)
    harmony: str = "keep"                   # keep | color | rich | jazz
    phrasing: list[str] = field(default_factory=lambda: ["memorable melody", "smooth phrasing"])
    bpm: int | None = 96
    key: str | None = None
    extra: str = ""                         # free text appended verbatim
    override: str | None = None             # user-edited final string (wins when set)

    @classmethod
    def from_dict(cls, data: dict | None) -> StyleFields:
        data = dict(data or {})
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self):
        return asdict(self)


def _vocal(f: StyleFields) -> str:
    if f.gender == "none":
        return ""
    noun = {"female": "female vocal", "male": "male vocal", "duet": "male and female duet vocals",
            "choir": "choir vocals"}.get(f.gender, f"{f.gender} vocal")
    timbre = " ".join(t for t in f.timbre[:2])
    parts = [f"{timbre} {noun}".strip()]
    delivery = {"controlled": DELIVERY_DEFAULT, "relaxed": "relaxed delivery", "intimate": "intimate delivery",
                "powerful": "powerful but controlled delivery", "rhythmic": "rhythmic rap delivery"}.get(
        f.delivery, f.delivery)
    if delivery:
        parts.append(delivery)
    return ", ".join(parts)


def is_instrumental(f: StyleFields | None) -> bool:
    return bool(f) and f.gender == "none"


def compose(f: StyleFields, lyric_language: str = "en") -> str:
    if f.override:
        return f.override.strip()
    if is_instrumental(f):
        # Official phrasing for instrumentals: "gentle piano instrumental music for reading, no vocals"
        parts = list(f.genres[:3]) + ["instrumental"] + f.moods[:2]
        if f.instruments:
            parts.append(_join(f.instruments[:5]))
        parts += f.production[:2]
        if HARMONY.get(f.harmony):
            parts.append(HARMONY[f.harmony])
        parts += [p for p in f.phrasing[:3] if p not in ("clear diction", "gentle phrase endings")]
        if f.key:
            parts.append(f"in {f.key}")
        if f.extra.strip():
            parts.append(f.extra.strip().strip(","))
        if f.bpm:
            parts.append(f"{int(f.bpm)} BPM")
        parts.append("no vocals")
        return ", ".join(p for p in parts if p)
    language = f.language
    if language == "auto":
        language = {"zh": "Chinese", "en": "English", "mixed": "Chinese and English"}.get(lyric_language, "English")
    parts = [language]
    parts += f.genres[:3]
    parts += f.moods[:2]
    vocal = _vocal(f)
    if vocal:
        parts.append(vocal)
    if f.instruments:
        parts.append(_join(f.instruments[:5]))
    parts += f.production[:2]
    if HARMONY.get(f.harmony):
        parts.append(HARMONY[f.harmony])
    parts += f.phrasing[:3]
    if f.key:
        parts.append(f"in {f.key}")
    if f.extra.strip():
        parts.append(f.extra.strip().strip(","))
    if f.bpm:
        parts.append(f"{int(f.bpm)} BPM")
    return ", ".join(p for p in parts if p)


def _join(items):
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


GENRES = {g["en"].lower(): g for g in VOCAB["genres"]}


def genre_info(style: str, fields: StyleFields | None = None) -> dict:
    """Genre facts that change how lyrics are judged: EDM category, half-time vocals."""
    names = [g.lower() for g in (fields.genres if fields else [])]
    low = style.lower()
    names += [name for name in GENRES if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", low)]
    found = [GENRES[n] for n in dict.fromkeys(names) if n in GENRES]
    return {"edm": any(g.get("cat") == "edm" for g in found),
            "half_time": any(g.get("half_time") for g in found) or "half-time vocals" in low,
            "max_bpm": 230 if any(g["en"] in ("speedcore", "frenchcore", "breakcore") for g in found)
            else 200 if any(g.get("cat") == "edm" for g in found) else 180,
            "genres": [g["en"] for g in found]}


def vocal_bpm(style: str, fields: StyleFields | None = None) -> float:
    """Tempo the singer actually phrases at. Fast EDM (artcore, hardcore, DnB...) is sung in half-time."""
    bpm = (fields.bpm if fields and fields.bpm else None) or bpm_in(style) or 96
    info = genre_info(style, fields)
    return bpm / 2 if info["half_time"] and bpm >= 140 else float(bpm)


def descriptors(style: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,，;；\n]+", style) if p.strip()]


def bpm_in(style: str) -> int | None:
    m = re.search(r"(\d{2,3})\s*bpm", style, re.I)
    return int(m.group(1)) if m else None


# =========================================================================== style lint (pre)
@dataclass
class StyleContext:
    style: str
    fields: StyleFields
    lyric_language: str = "en"
    has_lyrics: bool = True


def _has(words, text):
    return [w for w in words if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text, re.I)]


@register("style.empty", catalog="B6", stage="pre", severity="error", goal="variety",
          en="Style is empty", zh="风格为空")
def style_empty(r, ctx):
    if not ctx.style.strip():
        yield r.issue("Describe at least a language, a genre and a vocal.", "请至少描述语言、曲风和人声。")


@register("style.too_many", catalog="B6", stage="pre", severity="warn", goal="variety",
          en="Too many descriptors", zh="描述词太多")
def too_many(r, ctx):
    n = len(descriptors(ctx.style))
    if n > 12:
        yield r.issue(f"{n} descriptors: long tag lists dilute each other and the model follows none of them "
                      "well. Keep the 8-12 that matter most.",
                      f"共 {n} 个描述词。标签太多会互相稀释，模型哪个都跟不好，保留最重要的 8-12 个。")


@register("style.length", catalog="B6", stage="pre", severity="warn", goal="variety",
          en="Style text looks like prose or lyrics", zh="风格文本像散文或歌词")
def style_length(r, ctx):
    if len(ctx.style) > 320 or "\n" in ctx.style.strip():
        yield r.issue("Style should be a comma-separated list of short descriptors, not sentences or lyrics.",
                      "风格应是用逗号分隔的简短描述词，不要写成句子或歌词。")


@register("style.language", catalog="A10", stage="pre", severity="warn", goal="singing",
          en="Style language vs lyric language", zh="风格语言与歌词语言")
def style_language(r, ctx):
    s = ctx.style.lower()
    if is_instrumental(ctx.fields) and not ctx.has_lyrics:
        return
    says_zh = bool(re.search(r"chinese|mandarin|cantonese|c-pop|mandopop|中文|国语|华语", s))
    says_en = bool(re.search(r"(?<![a-z])english(?![a-z])|英文", s))
    if not says_zh and not says_en:
        yield r.issue("Name the language first (e.g. 'Chinese, ...'). It steers pronunciation.",
                      "请在开头写明语言（如 'Chinese, ...'），这会影响咬字发音。")
    elif ctx.lyric_language == "zh" and says_en and not says_zh:
        yield r.issue("Style says English but the lyrics are Chinese.", "风格写的是英文，但歌词是中文。",
                      severity="error")
    elif ctx.lyric_language == "en" and says_zh and not says_en:
        yield r.issue("Style says Chinese but the lyrics are English.", "风格写的是中文，但歌词是英文。",
                      severity="error")


@register("style.vocal", catalog="A12", stage="pre", severity="warn", goal="singing",
          en="Vocal description", zh="人声描述")
def style_vocal(r, ctx):
    s = ctx.style.lower()
    if not ctx.has_lyrics or is_instrumental(ctx.fields):
        return
    if not re.search(r"vocal|voice|singer|sung|choir|rap|男声|女声|人声|歌手", s):
        yield r.issue("Say who sings (e.g. 'warm female vocal'); otherwise the voice can change between takes.",
                      "请写明谁来唱（如 'warm female vocal'），否则不同版本的嗓音可能变来变去。")
    male, female = _has(["male", "man", "boy", "男声"], s), _has(["female", "woman", "girl", "女声"], s)
    if male and female and not re.search(r"duet|对唱|and female|and male", s):
        yield r.issue("Both male and female are mentioned without 'duet': the voice may switch mid-song.",
                      "同时写了男声和女声却没写“duet”，歌曲中途可能换人唱。")


@register("style.instrumental", catalog="A11", stage="pre", severity="error", goal="lyrics",
          en="Instrumental style with lyrics", zh="纯音乐风格却有歌词")
def style_instrumental(r, ctx):
    if ctx.has_lyrics and (is_instrumental(ctx.fields) or
                           re.search(r"instrumental(?! break)|no vocals?|without vocals?|纯音乐|无人声", ctx.style, re.I)):
        yield r.issue("Instrumental (no vocals) is selected but there are lyrics. YuE2 always sings the lyrics it is "
                      "given: delete the lines (keep only [Intro] / [Interlude] / [Outro] tags) or choose a vocal.",
                      "选择了纯音乐（无人声），但你写了歌词。YuE2 会演唱给它的所有歌词：请删除歌词（只保留 [Intro] / "
                      "[Interlude] / [Outro] 标签）或选择人声。")


@register("style.negation", catalog="B6", stage="pre", severity="hint", goal="variety",
          en="Negative descriptors", zh="否定式描述")
def style_negation(r, ctx):
    hits = re.findall(r"\b(?:no|without|not|avoid|never)\s+[a-z]+|不要\S+|没有\S+", ctx.style, re.I)
    hits = [h for h in hits if not re.match(r"no vocals?|without vocals?", h, re.I)]
    if hits:
        yield r.issue(f"Negations ({', '.join(hits[:3])}) are weak: naming a thing tends to add it. Describe "
                      "what you want instead (e.g. 'sparse acoustic arrangement').",
                      f"否定描述（{', '.join(hits[:3])}）效果很弱，提到某样东西反而容易把它加进去。请直接描述你想要的（如 'sparse acoustic arrangement'）。")


@register("style.artist", catalog="B6", stage="pre", severity="warn", goal="workflow",
          en="Artist names", zh="艺人名字")
def style_artist(r, ctx):
    s = ctx.style
    hits = [a for a in VOCAB["artists"] if re.search(rf"(?<![A-Za-z]){re.escape(a)}(?![A-Za-z])", s, re.I)]
    if re.search(r"in the style of|sounds? like|像\S+一样|模仿|风格像", s, re.I):
        hits.append("style-of phrase")
    if hits:
        yield r.issue(f"Avoid artist references ({', '.join(hits[:3])}): the model doesn't know them reliably, "
                      "and imitation is a legal risk for releases. Describe the sound instead.",
                      f"避免引用艺人（{', '.join(hits[:3])}）：模型并不可靠地认识他们，模仿也会给发行带来法律风险。请描述声音特点。")


@register("style.intensity", catalog="A15", stage="pre", severity="warn", goal="singing",
          en="Words that trigger shouting", zh="容易引发喊叫的词")
def style_intensity(r, ctx):
    hits = _has(["screaming", "scream", "shouting", "shout", "yelling", "aggressive", "belting", "belt",
                 "explosive", "intense", "raging", "嘶吼", "呐喊", "爆发"], ctx.style)
    soft = _has(["ballad", "acoustic", "lo-fi", "lofi", "folk", "jazz", "r&b", "bossa", "lullaby", "ambient",
                 "piano", "soft", "chill", "民谣", "抒情"], ctx.style)
    if hits:
        yield r.issue(f"'{hits[0]}' pushes the singer toward sudden shouted line endings"
                      f"{' (especially in a soft genre)' if soft else ''}. Prefer 'powerful but controlled delivery, "
                      "smooth phrasing, gentle phrase endings'.",
                      f"“{hits[0]}”容易让歌手在句尾突然喊出来{'（在柔和曲风中尤其明显）' if soft else ''}。"
                      "建议改为 'powerful but controlled delivery, smooth phrasing, gentle phrase endings'。",
                      severity="warn" if soft else "hint")


@register("style.bpm", catalog="B5", stage="pre", severity="hint", goal="variety",
          en="Tempo", zh="速度")
def style_bpm(r, ctx):
    stated = bpm_in(ctx.style)
    if stated is None:
        yield r.issue("Add a tempo (e.g. '96 BPM'); it's how the official examples fix the groove.",
                      "加上速度（如 '96 BPM'），官方示例就是这样确定律动的。")
    elif ctx.fields.bpm and abs(stated - ctx.fields.bpm) > 2 and ctx.fields.override:
        yield r.issue(f"The text says {stated} BPM but the tempo field is {ctx.fields.bpm}.",
                      f"文本写的是 {stated} BPM，但速度设置是 {ctx.fields.bpm}。")
    else:
        info = genre_info(ctx.style, ctx.fields)
        if stated and not 50 <= stated <= info["max_bpm"]:
            yield r.issue(f"{stated} BPM is unusual for {', '.join(info['genres'][:2]) or 'this style'}; the model is "
                          f"most stable up to ~{info['max_bpm']}.",
                          f"{stated} BPM 对这种风格来说不太常见，模型在 {info['max_bpm']} 以内最稳定。")
        elif stated and stated >= 140 and info["half_time"]:
            yield r.issue(f"Fast {info['genres'][0] if info['genres'] else 'EDM'}: lyrics are checked at the half-time "
                          f"feel ({stated / 2:.0f} BPM), the way vocals are usually sung over {stated} BPM drums. "
                          "Adding 'half-time vocals over fast drums' helps the model do the same.",
                          f"快速电子曲风：歌词密度按半拍律动（{stated / 2:.0f} BPM）检查，这是 {stated} BPM 鼓点上常见的唱法。"
                          "在风格中加入 'half-time vocals over fast drums' 可以帮助模型这样处理。",
                          severity="hint")


def lint_style(style: str, fields: StyleFields, lyric_language: str, has_lyrics: bool) -> list[dict]:
    ctx = StyleContext(style=style, fields=fields, lyric_language=lyric_language, has_lyrics=has_lyrics)
    return [i.to_dict() for i in run("pre", ctx, prefix="style.")]
