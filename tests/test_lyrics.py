"""Pre-generation lyric rules: every catalog item that has a mechanical check."""
import pytest

from yuestudio.lyrics import normalize as N
from yuestudio.lyrics import syllables
from yuestudio.lyrics.doc import parse
from yuestudio.lyrics.lint import LintContext, lint
from yuestudio.lyrics.tags import canonical, parse_repeat_line, repeat_count
from yuestudio.lyrics.text import en_number, line_language, zh_number


def rules(text, **ctx):
    return {i["rule"] for i in lint(text, LintContext(**ctx))["issues"]}


@pytest.mark.parametrize("raw,expected", [
    ("Verse 1", "Verse"), ("verse2", "Verse"), ("主歌", "Verse"), ("副歌", "Chorus"), ("Hook", "Chorus"),
    ("Pre Chorus", "Pre-Chorus"), ("导歌", "Pre-Chorus"), ("Guitar Solo", "Interlude"), ("间奏", "Interlude"),
    ("drop", "Interlude"), ("桥段", "Bridge"), ("Ending", "Outro"), ("Verse (Rap)", "Verse"), ("Banana", None),
])
def test_tag_canonical(raw, expected):
    assert canonical(raw) == expected


def test_repeat_shorthand():
    assert repeat_count("[Chorus x2]") == 2
    assert repeat_count("[副歌 ×3]") == 3
    assert parse_repeat_line("(Repeat Chorus x2)") == ("Chorus", 2)
    assert parse_repeat_line("副歌重复") == ("Chorus", 1)


def test_expanded_structure_writes_repeats_out():
    doc = parse("[Verse]\na b c\n\n[Chorus x2]\nla la\n\n(Repeat Chorus)\n")
    seq = [s.tag for s in doc.expanded()]
    assert seq == ["Verse", "Chorus", "Chorus"]
    assert len(doc.expanded()[1].lines) == 2  # x2 written out inside one chorus


@pytest.mark.parametrize("n,zh,en", [(2024, "二零二四", "twenty twenty-four"), (15, "十五", "fifteen"),
                                     (105, "一百零五", "one hundred five"), (1999, "一九九九", "nineteen ninety-nine")])
def test_numbers(n, zh, en):
    assert zh_number(str(n)) == zh
    assert en_number(str(n)) == en


def test_house_style_sung_text():
    sung, changes = N.sing_line("女：城市的灯火，慢慢亮起来！~~ 😊")
    assert sung == "城市的灯火 慢慢亮起来"
    assert {"speaker", "punctuation", "emoji"} <= set(changes)
    assert N.sing_line("(oh yeah) Streetlights FLICKER on the avenue!!")[0] == "oh yeah Streetlights flicker on the avenue"
    assert N.sing_line("I love you *whisper*")[0] == "I love you"


def test_syllables():
    assert syllables.count("城市的灯火") == 5
    assert syllables.count("beautiful") == 3
    assert syllables.count("Every window glowing") in (6, 7)  # "ev-(e)-ry" is sung both ways
    assert line_language("你好 world") == "mixed"


def test_lint_catches_the_catalog():
    text = ("[Verse 1]\n城市的灯火，慢慢亮起来！\n我在2024年的雨里 想起你~~\nStreetlights FLICKER on the avenue\n"
            "女：你说过 & 我们会一起走\n visit www.example.com\n\n[Chorus x2]\nla la la la\nla la la la\nla la la la\n")
    found = rules(text)
    for rule in ("lyrics.tag.alias", "lyrics.zh_punct", "lyrics.digits", "lyrics.tilde", "lyrics.caps",
                 "lyrics.speaker_label", "lyrics.symbols", "lyrics.url", "lyrics.tag.repeat", "lyrics.repeat.lines",
                 "lyrics.filler", "lyrics.structure.no_outro"):
        assert rule in found, rule


def test_clean_lyrics_have_no_warnings(lyrics):
    issues = lint(lyrics, LintContext(bpm=96))["issues"]
    assert not [i for i in issues if i["severity"] in ("error", "warn")], issues


def test_density_uses_half_time_for_fast_edm():
    text = "[Verse]\nRunning through the neon lights tonight we never ever stop\n\n[Outro]\n"
    assert "lyrics.density" in rules(text, bpm=175)
    assert "lyrics.density" not in rules(text, bpm=175, vocal_bpm=87.5)


def test_empty_lyrics_block_unless_instrumental():
    assert any(i["severity"] == "error" for i in lint("", LintContext())["issues"])
    out = lint("", LintContext(instrumental=True))
    assert not out["issues"] and out["sung"].startswith("[Intro]")


def test_sung_mapping_points_back_to_display_lines(lyrics):
    doc = parse(lyrics)
    sung, mapping = N.sung_lyrics(doc)
    assert sung.startswith("[Intro]\n\n[Verse]")
    for m in mapping:
        assert doc.lines[m.display_index] == m.display
