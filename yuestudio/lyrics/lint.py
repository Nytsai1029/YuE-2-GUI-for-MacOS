"""Pre-generation lyric rules (catalog A1-A17, B1, B7, D4). Every rule offers a fix
where one is mechanical; the sung-text builder applies the safe ones automatically."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..rules import Fix, run
from ..rules import rule as register
from . import normalize as N
from .doc import LyricDoc, parse
from .duration import COMFORT_SECONDS, SEMANTIC_MAX, estimate
from .tags import CANONICAL, VOCAL_REQUIRED
from .text import RE_DIGITS, RE_EMOJI, RE_URL, SYMBOL_WORDS, line_language

ZH_LINE_WARN, ZH_LINE_ERROR = 14, 20
EN_LINE_WARN, EN_LINE_ERROR = 14, 20
DENSITY_WARN = 5.0          # syllables per second over a two-bar line
POLYPHONES = {  # common lyric words whose default reading is easy to get wrong
    "长": "zhǎng/cháng", "重": "zhòng/chóng", "行": "xíng/háng", "还": "hái/huán", "乐": "lè/yuè",
    "调": "diào/tiáo", "朝": "cháo/zhāo", "传": "chuán/zhuàn", "觉": "jué/jiào", "数": "shù/shǔ",
    "落": "luò/là", "曲": "qǔ/qū", "相": "xiāng/xiàng", "兴": "xìng/xīng", "应": "yīng/yìng",
    "空": "kōng/kòng", "弹": "tán/dàn", "散": "sàn/sǎn", "为": "wèi/wéi", "着": "zhe/zháo",
}


INSTRUMENTAL_SKELETON = "[Intro]\n\n[Interlude]\n\n[Interlude]\n\n[Interlude]\n\n[Outro]\n"


def instrumental_skeleton(target: float | None, bpm: float, edm: bool = False) -> str:
    """Intro + N interludes + outro, with N chosen so the estimate lands near ``target``."""
    if not target:
        return INSTRUMENTAL_SKELETON
    best, best_err = INSTRUMENTAL_SKELETON, None
    for n in range(1, 16):
        text = "[Intro]\n\n" + "[Interlude]\n\n" * n + "[Outro]\n"
        err = abs(estimate(parse(text), bpm, edm=edm, instrumental=True).seconds - target)
        if best_err is None or err < best_err:
            best, best_err = text, err
    return best


@dataclass
class LintContext:
    bpm: float = 96.0
    vocal_bpm: float | None = None      # half-time feel for fast EDM (artcore, hardcore, DnB...)
    edm: bool = False
    instrumental: bool = False          # "no lyrics" mode: only instrumental section tags
    target_seconds: float | None = None  # requested song length
    language: str | None = None
    lexicon: dict[str, str] = field(default_factory=dict)
    style: str = ""


def _line_fix(label_en, label_zh, index, new):
    return Fix(label={"en": label_en, "zh": label_zh}, lines={index: new})


def _each_sung(doc: LyricDoc):
    for si, section in enumerate(doc.sections):
        for line in section.lines:
            yield si, section, line


# =========================================================================== A2: tags & structure
@register("lyrics.tag.alias", catalog="A2", stage="pre", severity="warn", goal="lyrics",
          en="Section tags use the official names", zh="段落标签使用官方名称")
def tag_alias(r, doc, ctx):
    """[Verse 1], [副歌], [Hook] ... are rewritten to the vocabulary YuE2 was trained with."""
    for section in doc.sections:
        if section.tag_line is None or section.tag is None:
            continue
        official = f"[{section.tag}]"
        current = doc.lines[section.tag_line].strip()
        if current != official and section.repeat == 1:
            yield r.issue(f"Use the official tag {official} (was {current}).",
                          f"请使用官方标签 {official}（当前为 {current}）。",
                          line=section.tag_line, fix=_line_fix(f"Change to {official}", f"改为 {official}",
                                                               section.tag_line, official))


@register("lyrics.tag.unknown", catalog="A2", stage="pre", severity="warn", goal="lyrics",
          en="Unknown section tag", zh="无法识别的段落标签")
def tag_unknown(r, doc, ctx):
    for section in doc.sections:
        if section.tag_line is not None and section.tag is None:
            options = ", ".join(f"[{c}]" for c in CANONICAL)
            yield r.issue(f"[{section.raw_tag}] is not a section the model knows. Use one of {options}. "
                          "Unknown tags may be sung as words.",
                          f"[{section.raw_tag}] 不是模型认识的段落名，请改用 {options}。未知标签可能被当作歌词唱出来。",
                          line=section.tag_line,
                          fix=_line_fix("Change to [Verse]", "改为 [Verse]", section.tag_line, "[Verse]"))


@register("lyrics.tag.missing", catalog="A2", stage="pre", severity="warn", goal="lyrics",
          en="Lyrics without a section tag", zh="歌词缺少段落标签")
def tag_missing(r, doc, ctx):
    for section in doc.sections:
        if section.tag_line is None and section.lines:
            first = section.lines[0]
            yield r.issue("These lines have no section tag; the model plans structure from tags.",
                          "这些歌词前没有段落标签，模型依据标签来安排结构。",
                          line=first.index,
                          fix=_line_fix("Insert [Verse] above", "在上方插入 [Verse]", first.index,
                                        "[Verse]\n" + first.text))


@register("lyrics.tag.repeat", catalog="A2", stage="pre", severity="warn", goal="lyrics",
          en="Write repeated sections out in full", zh="重复段落请完整写出")
def tag_repeat(r, doc, ctx):
    """Repeat shorthand ("[Chorus x2]", "(Repeat Chorus)", "副歌重复") is sung literally or ignored.
    The official examples always spell every occurrence out."""
    for section in doc.sections:
        if section.repeat > 1 and section.tag_line is not None:
            body = [line.text for line in section.lines]
            block = "\n".join(body)
            new = f"[{section.tag or 'Chorus'}]\n" + "\n\n".join([block] * section.repeat)
            fix = Fix(label={"en": f"Write it out {section.repeat}×", "zh": f"完整写出 {section.repeat} 遍"},
                      lines={section.tag_line: new, **{line.index: None for line in section.lines}})
            yield r.issue(f"'{doc.lines[section.tag_line].strip()}' is shorthand the model cannot expand.",
                          f"“{doc.lines[section.tag_line].strip()}”是模型无法展开的简写。",
                          line=section.tag_line, fix=fix)
    last = {}
    for section in doc.sections:
        if section.tag:
            last[section.tag] = section
    for d in doc.repeats:
        source = last.get(d.tag)
        replacement = None
        if source and source.lines:
            chunk = f"[{d.tag}]\n" + "\n".join(line.text for line in source.lines)
            replacement = "\n\n".join([chunk] * d.count)
        yield r.issue(f"'{doc.lines[d.index].strip()}' will not repeat anything; paste the {d.tag} again instead.",
                      f"“{doc.lines[d.index].strip()}”不会让模型重复，请把{d.tag}再完整写一遍。",
                      line=d.index,
                      fix=_line_fix(f"Paste the {d.tag} here", f"在此粘贴{d.tag}", d.index, replacement)
                      if replacement else None)


@register("lyrics.structure.blank", catalog="A2", stage="pre", severity="hint", goal="lyrics",
          en="Blank line between sections", zh="段落之间空一行")
def structure_blank(r, doc, ctx):
    for section in doc.sections:
        if section.tag_line and not section.blank_before:
            yield r.issue("Leave a blank line before each section tag (official format).",
                          "每个段落标签前空一行（官方格式）。", line=section.tag_line,
                          fix=_line_fix("Insert blank line", "插入空行", section.tag_line,
                                        "\n" + doc.lines[section.tag_line]))


@register("lyrics.structure.empty_vocal", catalog="A11", stage="pre", severity="warn", goal="lyrics",
          en="Sung section without lyrics", zh="需要演唱的段落没有歌词")
def structure_empty(r, doc, ctx):
    for section in doc.sections:
        if section.tag in VOCAL_REQUIRED and not section.lines and section.tag_line is not None:
            yield r.issue(f"[{section.tag}] is empty. Empty tags mean an instrumental passage; use [Interlude] "
                          "for that, or add the lines.",
                          f"[{section.tag}] 是空的。空标签表示纯音乐段落，这种情况请用 [Interlude]，否则请补上歌词。",
                          line=section.tag_line,
                          fix=_line_fix("Change to [Interlude]", "改为 [Interlude]", section.tag_line, "[Interlude]"))


@register("lyrics.structure.lyrics_in_instrumental", catalog="A11", stage="pre", severity="hint", goal="lyrics",
          en="Lyrics inside an instrumental section", zh="纯音乐段落里写了歌词")
def lyrics_in_instrumental(r, doc, ctx):
    for section in doc.sections:
        if section.tag in ("Intro", "Interlude") and section.lines and section.tag_line is not None:
            yield r.issue(f"Lines under [{section.tag}] will be sung. Leave it empty for an instrumental "
                          "passage, or tag the lines as a sung section.",
                          f"[{section.tag}] 下的歌词会被唱出来。想要纯音乐就留空，否则请改为演唱段落。",
                          line=section.tag_line)


@register("lyrics.structure.no_chorus", catalog="B2", stage="pre", severity="warn", goal="variety",
          en="No chorus", zh="没有副歌")
def no_chorus(r, doc, ctx):
    if ctx.instrumental:
        return
    sung = [s for s in doc.sections if s.lines]
    if len(sung) >= 2 and not any(s.tag == "Chorus" for s in doc.sections):
        yield r.issue("There is no [Chorus]. Without a hook section the model often loops the verse melody.",
                      "没有 [Chorus]。缺少副歌时，模型常常反复使用主歌旋律。")


@register("lyrics.structure.no_outro", catalog="B7", stage="pre", severity="hint", goal="variety",
          en="No ending section", zh="没有结尾段落")
def no_outro(r, doc, ctx):
    if doc.sections and not any(s.tag == "Outro" for s in doc.sections):
        last = max((line.index for s in doc.sections for line in s.lines), default=len(doc.lines) - 1)
        yield r.issue("Add an [Outro] so the song resolves instead of stopping abruptly.",
                      "加一个 [Outro]，让歌曲自然收尾而不是戛然而止。", line=last,
                      fix=_line_fix("Append empty [Outro]", "在末尾添加空的 [Outro]", last,
                                    doc.lines[last] + "\n\n[Outro]"))


# =========================================================================== A17 / B1: repetition
@register("lyrics.repeat.adjacent", catalog="A17", stage="pre", severity="warn", goal="variety",
          en="Same section twice in a row", zh="同一段落连续出现两次")
def adjacent_duplicate(r, doc, ctx):
    """Identical back-to-back sections invite the model to keep going (sung 3x)."""
    seq = doc.expanded()
    for a, b in zip(seq, seq[1:]):
        if a.lines and b.lines and a.text().strip() == b.text().strip() and b.tag_line is not None:
            yield r.issue(f"This [{b.tag}] repeats the previous one word for word. Back-to-back copies often "
                          "turn into a third repetition. Put another section between them or vary the lines.",
                          f"这段 [{b.tag}] 与上一段一字不差。连续重复容易让模型再唱第三遍，建议中间插入其他段落或改写几句。",
                          line=b.tag_line)


@register("lyrics.repeat.verses", catalog="B1", stage="pre", severity="warn", goal="variety",
          en="Identical verses", zh="主歌完全相同")
def identical_verses(r, doc, ctx):
    seen = {}
    for section in doc.sections:
        if section.tag in ("Verse", "Bridge", "Pre-Chorus") and section.lines:
            key = section.text().strip()
            if key in seen and section.tag_line is not None:
                yield r.issue("This section is identical to an earlier one. Repeated verses make the whole "
                              "song feel like a loop; only choruses should repeat.",
                              "这一段与前面完全相同。重复的主歌会让整首歌像在循环，通常只有副歌应该重复。",
                              line=section.tag_line)
            seen.setdefault(key, section)


@register("lyrics.repeat.lines", catalog="B1", stage="pre", severity="warn", goal="variety",
          en="Same line repeated many times", zh="同一句歌词重复多次")
def repeated_lines(r, doc, ctx):
    for section in doc.sections:
        run_start, count = 0, 1
        lines = section.lines
        for i in range(1, len(lines) + 1):
            same = i < len(lines) and N.whitespace(lines[i].text) == N.whitespace(lines[i - 1].text)
            if same:
                count += 1
                continue
            if count >= 3:
                first = lines[run_start]
                yield r.issue(f"'{first.text.strip()}' repeats {count}× in a row: a loop risk. Two is usually enough.",
                              f"“{first.text.strip()}”连续出现 {count} 次，容易导致循环，通常两次就够了。",
                              line=first.index)
            run_start, count = i, 1


@register("lyrics.bridge.missing", catalog="B1", stage="pre", severity="hint", goal="variety",
          en="Long song without a bridge", zh="长歌曲没有桥段")
def missing_bridge(r, doc, ctx):
    est = estimate(doc, ctx.vocal_bpm or ctx.bpm, edm=ctx.edm)
    if est.seconds > 180 and not any(s.tag == "Bridge" for s in doc.sections):
        yield r.issue(f"About {est.seconds / 60:.1f} min without a [Bridge]: a contrasting section keeps "
                      "long songs from feeling repetitive.",
                      f"约 {est.seconds / 60:.1f} 分钟却没有 [Bridge]，加一段对比性的桥段能避免长歌显得重复。")


# =========================================================================== A3: not-to-be-sung text
@register("lyrics.stage_direction", catalog="A3", stage="pre", severity="warn", goal="lyrics",
          en="Stage directions inside lyrics", zh="歌词里有舞台提示")
def stage_directions(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        cleaned = N.strip_stage_directions(line.text)
        if cleaned != N.whitespace(line.text) and cleaned != line.text.strip():
            yield r.issue("Directions like (guitar solo), *whisper* or [spoken] can be sung as words. "
                          "Describe delivery in the Style instead.",
                          "(guitar solo)、*whisper*、[spoken] 这类提示可能被当作歌词唱出来，演唱方式请写在风格里。",
                          line=line.index, fix=_line_fix("Remove direction", "删除提示", line.index, cleaned or None))


@register("lyrics.speaker_label", catalog="A3", stage="pre", severity="warn", goal="singing",
          en="Singer labels in lyrics", zh="歌词里有演唱者标注")
def speaker_labels(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        stripped = N.strip_speaker(line.text)
        if stripped != line.text:
            yield r.issue("Per-line singer labels (女:, Male:, 合:) aren't supported and may be sung. "
                          "Describe a duet in the Style instead.",
                          "不支持逐句指定演唱者（女:、Male:、合:），标注可能被唱出来。如需对唱请在风格中描述。",
                          line=line.index, fix=_line_fix("Remove label", "删除标注", line.index, stripped))


@register("lyrics.backing", catalog="A3", stage="pre", severity="hint", goal="lyrics",
          en="Parenthesised backing vocals", zh="括号里的和声歌词")
def backing(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if N.RE_PAREN.search(line.text) and N.strip_stage_directions(line.text) == N.whitespace(line.text):
            yield r.issue("Parentheses aren't understood as backing vocals. The singer gets these words "
                          "inline (without parentheses); remove them if they shouldn't be sung.",
                          "括号不会被理解为和声。歌手会把括号里的词直接唱出来（去掉括号）；不需要唱的请删除。",
                          line=line.index,
                          fix=_line_fix("Remove the part in parentheses", "删除括号内容", line.index,
                                        N.drop_backing(line.text)))


# =========================================================================== A4: unsingable tokens
@register("lyrics.digits", catalog="A4", stage="pre", severity="warn", goal="lyrics",
          en="Digits in lyrics", zh="歌词里有阿拉伯数字")
def digits(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if RE_DIGITS.search(line.text):
            fixed = N.spell_numbers(line.text)
            yield r.issue("Digits are read unpredictably. Spell the number the way it should be sung.",
                          "数字的读法不可控，请按想唱的方式写成文字。",
                          line=line.index, fix=_line_fix(f"Spell out: {fixed.strip()}", f"写成：{fixed.strip()}",
                                                         line.index, fixed))


@register("lyrics.symbols", catalog="A4", stage="pre", severity="warn", goal="lyrics",
          en="Symbols in lyrics", zh="歌词里有符号")
def symbols(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if any(ch in SYMBOL_WORDS for ch in line.text):
            fixed = N.spell_symbols(line.text)
            yield r.issue("Symbols like & % @ are not sung reliably. Write the word.",
                          "& % @ 这类符号唱不准，请写成文字。",
                          line=line.index, fix=_line_fix("Spell out symbols", "写成文字", line.index, fixed))


@register("lyrics.emoji", catalog="A4", stage="pre", severity="warn", goal="lyrics",
          en="Emoji or decorative symbols", zh="表情或装饰符号")
def emoji(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if RE_EMOJI.search(line.text) or any(ch in N.DECOR for ch in line.text if ch not in "~～"):
            yield r.issue("Emoji and decorative symbols confuse the singer.", "表情和装饰符号会干扰演唱。",
                          line=line.index, fix=_line_fix("Remove", "删除", line.index, N.strip_emoji_decor(line.text)))


@register("lyrics.url", catalog="A4", stage="pre", severity="error", goal="lyrics",
          en="Link or e-mail address", zh="链接或邮箱地址")
def url(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if RE_URL.search(line.text):
            yield r.issue("Links and e-mail addresses can't be sung. Remove or rewrite them.",
                          "链接和邮箱无法演唱，请删除或改写。",
                          line=line.index, fix=_line_fix("Remove link", "删除链接", line.index, N.strip_urls(line.text)))


@register("lyrics.acronym", catalog="A4", stage="pre", severity="hint", goal="singing",
          en="Acronym pronunciation", zh="缩写的读法")
def acronym(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        for m in re.finditer(r"\b[A-Z]{2,3}\b", line.text):
            word = m.group(0)
            if word in N.KEEP_CAPS or word in ctx.lexicon:
                continue
            yield r.issue(f"How should '{word}' be sung? Letter by letter usually needs spaces ({' '.join(word)}). "
                          "Add a lexicon entry to fix it for every song.",
                          f"“{word}”要怎么唱？逐个字母读通常需要写成 {' '.join(word)}。可以在词库中统一设置读法。",
                          line=line.index, start=m.start(), end=m.end(),
                          fix=_line_fix(f"Sing as {' '.join(word)}", f"唱作 {' '.join(word)}", line.index,
                                        line.text[:m.start()] + " ".join(word) + line.text[m.end():]))


# =========================================================================== A5: house style
@register("lyrics.zh_punct", catalog="A5", stage="pre", severity="warn", goal="lyrics",
          en="Punctuation in Chinese lines", zh="中文歌词里有标点")
def zh_punct(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        lang = line_language(line.text)
        if lang in ("zh", "mixed"):
            fixed = N.zh_punctuation(line.text)
            if fixed != line.text.strip():
                yield r.issue("Official lyrics use no punctuation; a single space marks a breath.",
                              "官方格式的歌词不用标点，用一个空格表示换气。",
                              line=line.index, fix=_line_fix("Apply house style", "改为官方格式", line.index, fixed))


@register("lyrics.en_punct", catalog="A5", stage="pre", severity="hint", goal="lyrics",
          en="Punctuation in English lines", zh="英文歌词里有标点")
def en_punct(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if line_language(line.text) == "en":
            fixed = N.en_punctuation(line.text)
            if fixed != line.text.strip() and re.search(r"[,.;:!?…\"“”]", line.text):
                yield r.issue("Punctuation isn't sung; line breaks carry the phrasing.",
                              "标点不会被唱出来，断句靠换行。",
                              line=line.index, fix=_line_fix("Remove punctuation", "删除标点", line.index, fixed))


@register("lyrics.whitespace", catalog="A5", stage="pre", severity="hint", goal="lyrics",
          en="Irregular spacing", zh="空格不规范")
def spacing(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        fixed = N.whitespace(line.text)
        if fixed != line.text:
            yield r.issue("Extra, leading or full-width spaces.", "多余、行首或全角空格。",
                          line=line.index, fix=_line_fix("Tidy spaces", "整理空格", line.index, fixed))


# =========================================================================== A6 / A16: fit & density
@register("lyrics.line_length", catalog="A6", stage="pre", severity="warn", goal="singing",
          en="Line too long", zh="单句过长")
def line_length(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        sung, _ = N.sing_line(line.text)
        lang = line_language(sung)
        n = len(re.findall(r"[㐀-鿿]", sung)) if lang == "zh" else line.syllables
        warn, err = (ZH_LINE_WARN, ZH_LINE_ERROR) if lang == "zh" else (EN_LINE_WARN, EN_LINE_ERROR)
        if n > warn:
            split = _split_line(line.text)
            unit_en, unit_zh = ("characters", "字") if lang == "zh" else ("syllables", "个音节")
            yield r.issue(f"{n} {unit_en} in one line: the singer will rush or drop words. Official lines are "
                          f"{'8-12 characters' if lang == 'zh' else '6-12 syllables'}.",
                          f"一句有 {n} {unit_zh}，歌手会赶拍或漏词。官方示例每句"
                          f"{'8-12 个字' if lang == 'zh' else '6-12 个音节'}。",
                          severity="error" if n > err else "warn", line=line.index,
                          fix=_line_fix("Split into two lines", "拆成两句", line.index, split) if split else None)


def _split_line(text: str) -> str | None:
    t = text.strip()
    mid = len(t) / 2
    candidates = [m.start() for m in re.finditer(r"[ ，,、;；]", t)]
    if not candidates:
        if re.search(r"[一-鿿]", t) and len(t) >= 8:
            cut = int(mid)
            return t[:cut] + "\n" + t[cut:]
        return None
    cut = min(candidates, key=lambda c: abs(c - mid))
    left, right = t[:cut].strip(" ，,、;；"), t[cut + 1:].strip(" ，,、;；")
    return left + "\n" + right if left and right else None


@register("lyrics.density", catalog="A6", stage="pre", severity="warn", goal="singing",
          en="Too many syllables for the tempo", zh="相对速度来说字太密")
def density(r, doc, ctx):
    bpm = ctx.vocal_bpm or ctx.bpm or 96
    two_bars = 8 * 60.0 / bpm
    for _, _section, line in _each_sung(doc):
        n = line.syllables
        rate = n / two_bars
        if rate > DENSITY_WARN and n > 6:
            yield r.issue(f"~{rate:.1f} syllables/second at {bpm:.0f} BPM: that's rap speed. Shorten the line, "
                          "split it, or lower the tempo.",
                          f"在 {bpm:.0f} BPM 下约每秒 {rate:.1f} 个字，已经是说唱速度。请缩短、拆句或降低速度。",
                          line=line.index, data={"rate": rate})


@register("lyrics.line_short", catalog="A16", stage="pre", severity="hint", goal="singing",
          en="Very short line in a sung section", zh="演唱段落里的句子太短")
def line_short(r, doc, ctx):
    for _, section, line in _each_sung(doc):
        if section.tag == "Outro":
            continue
        n = line.syllables
        if 0 < n <= 3 and N.is_filler_line(line.text) < 0.5:
            yield r.issue("A 1-3 syllable line under a full melody phrase invites humming or stretched vowels. "
                          "Merge it with a neighbour or accept a held note.",
                          "只有 1-3 个字的一句配上完整乐句，容易被哼唱或拖长元音。可以与相邻句合并。",
                          line=line.index)


@register("lyrics.filler", catalog="A16", stage="pre", severity="hint", goal="singing",
          en="Humming / filler syllables", zh="哼唱类语气词")
def filler(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if N.is_filler_line(line.text) >= 0.5:
            yield r.issue("Lines of 'hmm / la la / oh / 啦 / 嗯' tend to come out as wordless humming at odd pitches. "
                          "Use real words unless you want a vocalise here.",
                          "“hmm / la la / oh / 啦 / 嗯”这类句子常被唱成音高奇怪的无词哼唱，除非你想要哼唱，否则请写成真正的歌词。",
                          line=line.index)


@register("lyrics.tilde", catalog="A16", stage="pre", severity="warn", goal="singing",
          en="Tildes / stretch marks", zh="波浪号/拖音符号")
def tilde(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if re.search(r"[~～]|(.)\1{3,}", line.text):
            fixed = re.sub(r"[~～]+", "", line.text)
            fixed = re.sub(r"([A-Za-z一-鿿])\1{2,}", r"\1", fixed)
            yield r.issue("Tildes and stretched letters (ohhhh~) are a common trigger for humming instead of words.",
                          "波浪号和拉长的字母（ohhhh~）很容易让模型用哼唱代替歌词。",
                          line=line.index, fix=_line_fix("Remove stretch marks", "删除拖音符号", line.index, fixed))


# =========================================================================== A15: shouting triggers
@register("lyrics.caps", catalog="A15", stage="pre", severity="warn", goal="singing",
          en="SHOUTED words", zh="全大写（喊叫）")
def caps(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        fixed = N.calm_caps(line.text)
        if fixed != line.text:
            yield r.issue("ALL-CAPS emphasis can make the singer suddenly shout. Use normal case.",
                          "全大写的强调可能让歌手突然大喊，请使用正常大小写。",
                          line=line.index, fix=_line_fix("Normal case", "改为正常大小写", line.index, fixed))


@register("lyrics.exclaim", catalog="A15", stage="pre", severity="hint", goal="singing",
          en="Exclamation marks", zh="感叹号")
def exclaim(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if re.search(r"[!！]", line.text):
            fixed = re.sub(r"\s*[!！]+", "", line.text)
            yield r.issue("'!' at line ends correlates with shouted, rushed endings.",
                          "句尾的“！”容易导致结尾被喊出来、唱得很急。",
                          line=line.index, fix=_line_fix("Remove !", "删除！", line.index, fixed))


# =========================================================================== A10 / A14: language
@register("lyrics.mixed_language", catalog="A10", stage="pre", severity="hint", goal="singing",
          en="Chinese and English in one line", zh="同一句中英混合")
def mixed_language(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        if line_language(line.text) == "mixed":
            yield r.issue("Code-switching inside one line is pronounced less reliably. Keep each line in one "
                          "language when you can.",
                          "同一句中英混合时发音更不稳定，尽量让每句只用一种语言。", line=line.index)


@register("lyrics.traditional", catalog="A10", stage="pre", severity="warn", goal="singing",
          en="Traditional characters", zh="繁体字")
def traditional(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        simplified = N.to_simplified(line.text)
        if simplified != line.text:
            yield r.issue("Traditional characters are converted to simplified for the singer (the model is "
                          "most reliable with simplified). Your display text is kept.",
                          "繁体字会转换成简体交给歌手（模型对简体最稳定），显示文本保持不变。",
                          line=line.index,
                          fix=_line_fix("Convert to simplified", "转为简体", line.index, simplified))


@register("lyrics.polyphone", catalog="A10", stage="pre", severity="hint", goal="singing",
          en="Characters with two readings", zh="多音字")
def polyphone(r, doc, ctx):
    shown = 0
    try:
        from pypinyin import Style, pinyin
    except Exception:  # pragma: no cover
        return
    for _, _, line in _each_sung(doc):
        for m in re.finditer("|".join(POLYPHONES), line.text):
            if shown >= 6:
                return
            ch = m.group(0)
            if any(term in line.text and ch in term for term in ctx.lexicon):
                continue
            window = line.text[max(0, m.start() - 1):m.end() + 1]
            reading = " ".join(p[0] for p in pinyin(window, style=Style.TONE))
            shown += 1
            yield r.issue(f"'{ch}' can be read {POLYPHONES[ch]}. Expected here: {reading}. If the singer gets it "
                          "wrong, add a lexicon respelling.",
                          f"“{ch}”是多音字（{POLYPHONES[ch]}），这里预计读作 {reading}。如果唱错，可以在词库里设置替换写法。",
                          line=line.index, start=m.start(), end=m.end())


@register("lyrics.unsupported_language", catalog="A14", stage="pre", severity="warn", goal="singing",
          en="Language outside Chinese/English", zh="中英文以外的语言")
def unsupported_language(r, doc, ctx):
    for _, _, line in _each_sung(doc):
        lang = line_language(line.text)
        if lang in ("ja", "ko", "other"):
            yield r.issue("YuE2 is strongest in Chinese and English; other languages are uneven.",
                          "YuE2 在中文和英文上最稳定，其他语言效果参差不齐。", line=line.index)


# =========================================================================== D4 / A1: budget
@register("lyrics.budget", catalog="D4", stage="pre", severity="warn", goal="lyrics",
          en="Song length budget", zh="歌曲时长预算")
def budget(r, doc, ctx):
    if not doc.sung_lines:
        if not ctx.instrumental:
            yield r.issue("No lyrics yet. Write at least one sung section, or pick the Instrumental (no lyrics) preset.",
                          "还没有歌词。请至少写一个演唱段落，或选择“纯音乐（无歌词）”预设。", severity="error")
        return
    est = estimate(doc, ctx.vocal_bpm or ctx.bpm, style=ctx.style, edm=ctx.edm)
    if est.semantic_tokens > SEMANTIC_MAX:
        yield r.issue(f"About {est.seconds / 60:.1f} min at {ctx.bpm:.0f} BPM: longer than the model can generate "
                      "(~6 min). Later sections would be cut. Remove a repeated chorus or raise the tempo.",
                      f"在 {ctx.bpm:.0f} BPM 下约 {est.seconds / 60:.1f} 分钟，超过模型上限（约 6 分钟），后面的段落会被截掉。"
                      "请删掉一个重复的副歌或提高速度。",
                      severity="error", data=est.to_dict())
    elif est.seconds > COMFORT_SECONDS:
        yield r.issue(f"About {est.seconds / 60:.1f} min: above the ~5 min the model is tuned for; the risk of "
                      "skipped or repeated sections rises.",
                      f"约 {est.seconds / 60:.1f} 分钟，超过模型最擅长的 5 分钟左右，漏段或重复段落的风险会增加。",
                      data=est.to_dict())


@register("lyrics.target_length", catalog="B8", stage="pre", severity="warn", goal="lyrics",
          en="Lyrics vs target length", zh="歌词与目标时长")
def target_length(r, doc, ctx):
    """With a length target, the lyrics must roughly fill it: too few and the model stretches,
    repeats sections (A17) or hums; too many and it rushes or drops lines (A1/A6)."""
    if not ctx.target_seconds or not doc.sung_lines:
        return
    est = estimate(doc, ctx.vocal_bpm or ctx.bpm, style=ctx.style, edm=ctx.edm).seconds
    t = ctx.target_seconds
    fmt = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"  # noqa: E731
    if est > t * 1.2:
        yield r.issue(f"These lyrics need about {fmt(est)} but the target is {fmt(t)}: the singer would rush or drop "
                      "lines. Remove a section (e.g. a repeated chorus), raise the tempo, or raise the target.",
                      f"这些歌词大约需要 {fmt(est)}，而目标是 {fmt(t)}，歌手会赶拍或漏句。请删掉一个段落（如重复的副歌）、"
                      "提高速度，或放宽目标时长。", data={"estimate": est, "target": t})
    elif est < t * 0.7:
        yield r.issue(f"These lyrics fill about {fmt(est)} of the {fmt(t)} target. The harness will add instrumental "
                      "passages, but more sections (or a bridge) sound better than long gaps; otherwise the model tends "
                      "to repeat sections.",
                      f"这些歌词只能填满目标 {fmt(t)} 中的约 {fmt(est)}。系统会补充纯音乐段落，但多写一些段落（或桥段）"
                      "效果更好，否则模型容易重复段落。", severity="hint", data={"estimate": est, "target": t})


# =========================================================================== entry point
def lint(text: str, ctx: LintContext | None = None) -> dict:
    ctx = ctx or LintContext()
    doc = parse(text)
    issues = run("pre", doc, ctx, prefix="lyrics.")
    sung, mapping = N.sung_lyrics(doc, N.SungOptions(lexicon=ctx.lexicon))
    if ctx.instrumental and not mapping:
        if not doc.sections:
            sung = instrumental_skeleton(ctx.target_seconds, ctx.vocal_bpm or ctx.bpm, ctx.edm)
            doc = parse(sung)
    est = estimate(doc, ctx.vocal_bpm or ctx.bpm, sung_text=sung, style=ctx.style, edm=ctx.edm,
                   instrumental=ctx.instrumental and not mapping)
    return {"issues": [i.to_dict() for i in issues], "sung": sung, "target_seconds": ctx.target_seconds,
            "mapping": [m.__dict__ for m in mapping], "estimate": est.to_dict(),
            "language": doc.language(),
            "sections": [{"tag": s.tag, "raw_tag": s.raw_tag, "tag_line": s.tag_line,
                          "lines": [li.index for li in s.lines],
                          "syllables": [li.syllables for li in s.lines]} for s in doc.sections],
            "counts": {str(line.index): line.syllables for line in doc.sung_lines}}

