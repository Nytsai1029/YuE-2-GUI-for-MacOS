"""Analyze one generated ABC plan against the lyrics: scorecard, gates and issues."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from ..abc.score import Score, try_parse
from ..lyrics import syllables as S
from ..lyrics.doc import parse as parse_lyrics
from ..lyrics.duration import estimate
from ..lyrics.normalize import SungOptions, sing_line
from ..rules import rule as register
from ..rules import run
from . import fit as F
from . import metrics as M

GOAL_WEIGHTS = {"lyrics": 0.35, "singing": 0.25, "variety": 0.2, "harmony": 0.2}


@dataclass
class PlanContext:
    score: Score
    alignment: F.Alignment
    units: list[F.LyricUnit]
    harmony: dict
    repetition: dict
    melody: dict
    contrast: dict
    range: dict
    risks: list[dict]
    predicted_seconds: float
    lyric_seconds: float
    requested_bpm: float | None
    truncated: bool
    abc_to_tag: dict[int, str]
    lyric_dupes: bool
    instrumental: bool = False


def _sung_syllables(text: str, opts: SungOptions) -> int:
    return max(1, S.count(sing_line(text, opts)[0]))


def analyze(abc: str, lyrics_text: str, *, gender: str = "female", requested_bpm: float | None = None,
            vocal_bpm: float | None = None, truncated: bool = False, lexicon: dict | None = None,
            instrumental: bool = False) -> dict:
    score, error = try_parse(abc)
    if score is None:
        return {"ok": False, "error": error, "gates": {"parse": False}, "scorecard": _zero_card(),
                "score": 0.0, "issues": [{"rule": "plan.parse", "catalog": "A1", "severity": "error",
                                          "goal": "lyrics", "message": {"en": f"Unreadable score: {error}",
                                                                        "zh": f"乐谱无法解析：{error}"}}]}
    opts = SungOptions(lexicon=lexicon)
    doc = parse_lyrics(lyrics_text)
    expanded = doc.expanded()
    units = F.lyric_units(expanded, lambda t: _sung_syllables(t, opts))
    alignment = F.align(score, units)
    abc_to_tag = {}
    for m in alignment.matches:
        for ai in m.abc:
            abc_to_tag[ai] = units[m.lyric[0]].tag
    verse = [i for i, t in abc_to_tag.items() if t in ("Verse", "Pre-Chorus")] or \
        [s.index for s in score.sections if s.name == "verse"]
    chorus = [i for i, t in abc_to_tag.items() if t == "Chorus"] or [s.index for s in score.sections if s.name == "chorus"]
    fast = M.fast_ins_windows(score)
    baseline = median(fast) if fast else 0.0
    line_notes = F.notes_for_lines(score, units)
    syl_by_line = {lid: s for u in units for lid, s in zip(u.line_ids, u.syllables)}
    risks = M.line_risks(score, line_notes, syl_by_line, gender, baseline)
    lyric_est = estimate(doc, vocal_bpm or requested_bpm or score.bpm)
    texts = [s.text().strip() for s in expanded if s.lines]
    lyric_dupes = any(a == b for a, b in zip(texts, texts[1:]))
    ctx = PlanContext(score=score, alignment=alignment, units=units,
                      harmony=M.harmony(score, verse, chorus), repetition=M.repetition(score),
                      melody=M.melody(score.vocal), contrast=M.contrast(score, verse, chorus),
                      range=M.vocal_range(score, gender), risks=risks, predicted_seconds=score.seconds,
                      lyric_seconds=lyric_est.seconds, requested_bpm=requested_bpm, truncated=truncated,
                      abc_to_tag=abc_to_tag, lyric_dupes=lyric_dupes, instrumental=instrumental)
    issues = run("plan", ctx, prefix="plan.")
    card = scorecard(ctx)
    gates = {"parse": True, "not_truncated": not truncated,
             "no_missing_lyrics": not alignment.missing_lyric,
             "no_severe_cram": not [f for f in alignment.lines if f.ratio < 0.5 and f.syllables >= 4],
             "no_extra_sections": not [i for i in alignment.extra_abc if score.sections[i] and
                                       score.section_vocal(i)]}
    if instrumental:
        gates = {"parse": True, "not_truncated": not truncated, "no_vocal_melody": vocal_share(score) < 0.05}
    total = sum(card[g] * w for g, w in GOAL_WEIGHTS.items())
    repetition = dict(ctx.repetition)
    repetition.pop("_sim", None)
    return {
        "ok": True, "bpm": score.bpm, "key": score.key, "meter": list(score.meter),
        "predicted_seconds": round(score.seconds, 2), "lyric_seconds": round(lyric_est.seconds, 2),
        "bars": len(score.bars),
        "sections": [{"index": s.index, "name": s.name, "tag": abc_to_tag.get(s.index), "bars": len(s.bars),
                      "start": score.q2s(s.start), "end": score.q2s(s.end),
                      "vocal_notes": len(score.section_vocal(s.index))} for s in score.sections],
        "alignment": alignment.to_dict(), "harmony": ctx.harmony, "repetition": repetition,
        "melody": ctx.melody, "contrast": ctx.contrast, "range": ctx.range, "line_risks": risks,
        "scorecard": card, "gates": gates, "passed": all(gates.values()), "score": round(total, 1),
        "issues": [i.to_dict() for i in issues],
    }


def vocal_share(score: Score) -> float:
    total = len(score.vocal) + len(score.ins)
    return len(score.vocal) / total if total else 0.0


def _zero_card():
    return {g: 0.0 for g in GOAL_WEIGHTS}


def _clamp(x):
    return max(0.0, min(100.0, x))


def scorecard(ctx: PlanContext) -> dict:
    if ctx.instrumental:
        share = vocal_share(ctx.score)
        rep = ctx.repetition
        variety = 70 * min(1.0, rep["distinct_bar_ratio"] / 0.6) + 30 * (0 if rep["longest_identical_run"] >= 4 else 1)
        ins_melody = M.melody(ctx.score.ins)
        variety -= 15 if ins_melody.get("bland") else 0
        clean = 100 - 300 * share          # any melody in the Vocal voice will be hummed
        return {"lyrics": round(_clamp(clean), 1), "variety": round(_clamp(variety), 1),
                "harmony": round(_clamp(100 * ctx.harmony["richness"]), 1), "singing": round(_clamp(clean), 1)}
    lines = ctx.alignment.lines
    n = max(1, len(lines))
    cram = sum(1 for f in lines if f.ratio < 0.8) / n
    melisma = sum(1 for f in lines if f.ratio > 1.8) / n
    vocal_extra = [i for i in ctx.alignment.extra_abc if ctx.score.section_vocal(i)]
    lyrics = 100 - 40 * len(ctx.alignment.missing_lyric) - 25 * len(vocal_extra) - 60 * cram - 35 * melisma
    if ctx.truncated:
        lyrics = 0
    rep = ctx.repetition
    variety = 55 * min(1.0, rep["distinct_bar_ratio"] / 0.6) + 20 * (0 if rep["longest_identical_run"] >= 4 else 1)
    if ctx.contrast.get("available"):
        variety += 15 * (0 if ctx.contrast["flat"] else 1)
    else:
        variety += 8
    variety += 10 * (0 if ctx.melody.get("bland") else 1)
    variety -= 15 * len(rep["consecutive_duplicate_sections"]) if not ctx.lyric_dupes else 0
    harmony = 100 * ctx.harmony["richness"]
    risks = [r for r in ctx.risks if not r.get("empty")]
    rn = max(1, len(risks))
    a15 = sum(1 for r in risks if r["a15"]) / rn
    a16 = sum(1 for r in risks if r["a16"]) / rn
    singing = 100 - 45 * a15 - 35 * a16 - 30 * cram
    rg = ctx.range
    if rg.get("available"):
        singing -= 20 * (1 if rg["too_high"] or rg["too_low"] else 0) + 30 * rg["above_comfort"]
    return {"lyrics": round(_clamp(lyrics), 1), "variety": round(_clamp(variety), 1),
            "harmony": round(_clamp(harmony), 1), "singing": round(_clamp(singing), 1)}


# =========================================================================== plan rules
@register("plan.truncated", catalog="A1", stage="plan", severity="error", goal="lyrics",
          en="Score was cut off", zh="乐谱被截断")
def plan_truncated(r, ctx):
    if ctx.truncated:
        yield r.issue("The score hit its token limit; the end of the song is missing. It will be re-planned with a "
                      "bigger budget.", "乐谱达到了 token 上限，歌曲结尾缺失，会用更大的预算重新规划。")


@register("plan.missing_lyrics", catalog="A1", stage="plan", severity="error", goal="lyrics",
          en="Lyric section has no music", zh="有歌词段落没有对应旋律")
def plan_missing(r, ctx):
    for li in ctx.alignment.missing_lyric:
        u = ctx.units[li]
        yield r.issue(f"This {u.tag} has no melody in this plan: its lyrics would be lost. Pick another plan or "
                      "duplicate a section.",
                      f"这个方案里 {u.tag} 段落没有旋律，这些歌词会丢失。请换一个方案或复制段落。",
                      line=u.line_ids[0] if u.line_ids else None, section=li)


@register("plan.extra_section", catalog="A17", stage="plan", severity="warn", goal="lyrics",
          en="Extra sung section", zh="多出来的演唱段落")
def plan_extra(r, ctx):
    if ctx.instrumental:
        return
    for ai in ctx.alignment.extra_abc:
        sec = ctx.score.sections[ai]
        yield r.issue(f"The score has an extra '{sec.name or 'vocal'}' section with no lyrics of its own: it will be "
                      "sung as a repeat (2-3×) or hummed.",
                      f"乐谱多了一个没有对应歌词的“{sec.name or '演唱'}”段落，它会被重复演唱（2-3 遍）或被哼唱。",
                      section=ai, time=(ctx.score.q2s(sec.start), ctx.score.q2s(sec.end)))


@register("plan.duplicate_sections", catalog="A17", stage="plan", severity="warn", goal="variety",
          en="Same section back to back", zh="相同段落接连出现")
def plan_dupes(r, ctx):
    if ctx.instrumental:
        return
    if ctx.lyric_dupes:
        return
    for b in ctx.repetition["consecutive_duplicate_sections"]:
        sec = ctx.score.sections[b]
        yield r.issue("Two consecutive sections have the same melody although your lyrics don't repeat there.",
                      "两个相邻段落旋律相同，但你的歌词在这里并没有重复。",
                      section=b, time=(ctx.score.q2s(sec.start), ctx.score.q2s(sec.end)))


@register("plan.cram", catalog="A6", stage="plan", severity="warn", goal="singing",
          en="Too many syllables for the notes", zh="字多音少")
def plan_cram(r, ctx):
    for f in ctx.alignment.lines:
        if f.ratio < 0.8 and f.syllables >= 4:
            yield r.issue(f"{f.syllables} syllables on ~{f.notes} notes: the singer must squeeze or drop words.",
                          f"{f.syllables} 个字只有约 {f.notes} 个音，歌手只能挤着唱或漏字。",
                          line=f.line_id, time=(f.start, f.end), severity="warn" if f.ratio >= 0.6 else "error")


@register("plan.melisma", catalog="A16", stage="plan", severity="warn", goal="singing",
          en="Many more notes than syllables", zh="音比字多很多")
def plan_melisma(r, ctx):
    for f in ctx.alignment.lines:
        if f.ratio > 1.8:
            yield r.issue(f"~{f.notes} notes for {f.syllables} syllables: expect stretched vowels or wordless humming.",
                          f"约 {f.notes} 个音只有 {f.syllables} 个字，可能出现拖长元音或无词哼唱。",
                          line=f.line_id, time=(f.start, f.end))


@register("plan.phrase_end", catalog="A15", stage="plan", severity="warn", goal="singing",
          en="Risky line ending", zh="句尾有风险")
def plan_phrase_end(r, ctx):
    for risk in ctx.risks:
        if risk.get("empty") or not risk["a15"]:
            continue
        why_en, why_zh = [], []
        if risk["leap_end"] or risk["high_end"]:
            why_en.append("jumps to a high held last note")
            why_zh.append("最后一个音跳到高处并拖长")
        if risk["rushed_tail"]:
            why_en.append("ends in a run of very short notes")
            why_zh.append("结尾是一串很短的音")
        if risk["ins_burst"]:
            why_en.append(f"the band plays a fast fill ({risk['burst_notes']} quick notes) right as the line ends")
            why_zh.append(f"句子结束时伴奏突然快速加花（{risk['burst_notes']} 个快音）")
        yield r.issue("This line " + " and ".join(why_en) + ": a typical trigger for a shouted, rushed ending.",
                      "这一句" + "，".join(why_zh) + "，这很容易导致句尾被喊出来、唱得很急。",
                      line=risk["line"], time=(risk["start"], risk["end"]), data=risk)


@register("plan.odd_pitch", catalog="A16", stage="plan", severity="hint", goal="singing",
          en="Long note outside the harmony", zh="长音不在和声里")
def plan_odd(r, ctx):
    for risk in ctx.risks:
        if not risk.get("empty") and risk["odd_long_notes"]:
            yield r.issue("A long note sits outside the key/chord here; the model tends to hum or waver on these.",
                          "这里有一个不在调内或和弦内的长音，模型容易在这里哼唱或跑音。",
                          line=risk["line"], time=(risk["start"], risk["end"]))


@register("plan.range", catalog="A8", stage="plan", severity="warn", goal="singing",
          en="Vocal range", zh="音域")
def plan_range(r, ctx):
    if ctx.instrumental:
        return
    rg = ctx.range
    if not rg.get("available"):
        return
    if rg["too_high"] or rg["too_low"] or rg["suggest_transpose"]:
        direction = "high" if rg["center"] > sum(rg["comfort"]) / 2 else "low"
        t = rg["suggest_transpose"]
        yield r.issue(f"The melody sits {direction} for this voice (strain or mumbling). Transposing by {t:+d} semitones "
                      "centres it." if t else f"The melody reaches outside this voice's range ({direction}).",
                      f"旋律对这个声部来说偏{'高' if direction == 'high' else '低'}（容易吃力或含糊）。"
                      + (f"建议移调 {t:+d} 个半音。" if t else ""),
                      severity="warn" if rg["too_high"] or rg["too_low"] else "hint", data=rg)


@register("plan.loop", catalog="B1", stage="plan", severity="warn", goal="variety",
          en="Melody loops", zh="旋律循环")
def plan_loop(r, ctx):
    rep = ctx.repetition
    if rep["longest_identical_run"] >= 4:
        b = ctx.score.bars[rep["run_start_bar"] or 0]
        yield r.issue(f"The same bar repeats {rep['longest_identical_run']}× in a row.",
                      f"同一小节连续重复 {rep['longest_identical_run']} 次。", time=(ctx.score.q2s(b.start),
                                                                          ctx.score.q2s(b.start) + 4))
    if rep["distinct_bar_ratio"] < 0.35:
        yield r.issue(f"Only {rep['distinct_bar_ratio']:.0%} of sung bars are different: the song will feel repetitive.",
                      f"只有 {rep['distinct_bar_ratio']:.0%} 的演唱小节互不相同，歌曲会显得重复。")


@register("plan.verse_chorus_same", catalog="B2", stage="plan", severity="warn", goal="variety",
          en="Verse and chorus sound alike", zh="主歌和副歌太像")
def plan_vc(r, ctx):
    if ctx.instrumental:
        return
    sim = ctx.repetition["_sim"]
    verse = [i for i, t in ctx.abc_to_tag.items() if t in ("Verse", "Pre-Chorus")]
    chorus = [i for i, t in ctx.abc_to_tag.items() if t == "Chorus"]
    best = max((sim.get((min(a, b), max(a, b)), 0) for a in verse for b in chorus), default=0)
    if best > 0.6:
        yield r.issue("Verse and chorus share most of their melody; the chorus won't lift.",
                      "主歌和副歌的旋律大部分相同，副歌起不来。")
    elif ctx.contrast.get("available") and ctx.contrast["flat"]:
        yield r.issue("The chorus isn't higher or busier than the verse (no lift).", "副歌没有比主歌更高或更密集（没有推进感）。",
                      severity="hint")


@register("plan.simple_chords", catalog="B3", stage="plan", severity="warn", goal="harmony",
          en="Chords too simple", zh="和弦太简单")
def plan_chords(r, ctx):
    h = ctx.harmony
    if not h["chords"]:
        return
    if h["whole_song_loop"] or h["unique"] <= 4 or h["richness"] < 0.35:
        yield r.issue(f"{h['unique']} different chords" + (f", one {h['loop_period']}-bar loop for the whole song"
                                                            if h["whole_song_loop"] else "")
                      + ". Use 'Harmony colour' to enrich it without touching the melody.",
                      f"只有 {h['unique']} 种和弦" + ("，整首歌是同一个循环" if h["whole_song_loop"] else "")
                      + "。可以用“和声色彩”在不改旋律的情况下丰富和声。", data=h)
    elif h["verse_chorus_same"]:
        yield r.issue("Verse and chorus use the same progression.", "主歌和副歌用的是同一个和弦进行。", severity="hint")


@register("plan.bland_melody", catalog="B4", stage="plan", severity="hint", goal="variety",
          en="Bland melody", zh="旋律平淡")
def plan_bland(r, ctx):
    if ctx.instrumental:
        return
    if ctx.melody.get("bland"):
        yield r.issue(f"Narrow ({ctx.melody['range']} semitones) or static melody.",
                      f"旋律音域窄（{ctx.melody['range']} 个半音）或缺少起伏。")


@register("plan.tempo", catalog="B5", stage="plan", severity="warn", goal="variety",
          en="Tempo differs from request", zh="速度与要求不符")
def plan_tempo(r, ctx):
    want = ctx.requested_bpm
    got = ctx.score.bpm
    if want and all(abs(got - want * k) > max(4, want * k * 0.05) for k in (1, 0.5, 2)):
        yield r.issue(f"The plan is at {got} BPM but you asked for {want:.0f}. It can be corrected before rendering.",
                      f"方案速度是 {got} BPM，而你要求 {want:.0f}。可以在渲染前修正。", data={"got": got, "want": want})


@register("plan.length", catalog="B8", stage="plan", severity="warn", goal="lyrics",
          en="Unexpected length", zh="时长异常")
def plan_length(r, ctx):
    if ctx.instrumental:
        return
    est, got = ctx.lyric_seconds, ctx.predicted_seconds
    if est and got < est * 0.55:
        yield r.issue(f"The plan is only {got:.0f}s for lyrics that need ~{est:.0f}s: sections were compressed or skipped.",
                      f"方案只有 {got:.0f} 秒，而歌词大约需要 {est:.0f} 秒，段落可能被压缩或跳过。")
    elif est and got > est * 1.8:
        yield r.issue(f"The plan runs {got:.0f}s for lyrics that need ~{est:.0f}s: expect repeats or long gaps.",
                      f"方案长达 {got:.0f} 秒，而歌词大约只需 {est:.0f} 秒，可能会有重复或长时间空白。")


@register("plan.vocal_in_instrumental", catalog="A11", stage="plan", severity="warn", goal="lyrics",
          en="Melody given to the singer", zh="旋律被分配给了歌手")
def plan_vocal_in_instrumental(r, ctx):
    """Instrumental mode: any note in the Vocal voice will be hummed or sung as nonsense."""
    if not ctx.instrumental:
        return
    share = vocal_share(ctx.score)
    if share > 0:
        notes = ctx.score.vocal
        yield r.issue(f"{len(notes)} notes are in the singer's part ({share:.0%}); in an instrumental they come out as "
                      "humming or wordless singing. Prefer another score.",
                      f"有 {len(notes)} 个音在歌手声部（{share:.0%}），纯音乐里它们会变成哼唱或无词演唱，建议换一份乐谱。",
                      severity="warn" if share < 0.2 else "error",
                      time=(ctx.score.q2s(notes[0].onset), ctx.score.q2s(notes[-1].end)))
