"""Score model, edits and repairs must always produce valid native ABC and keep their
invariants (the engine's own parser is vendored and authoritative)."""
from fractions import Fraction

import pytest

from yuestudio.abc import display
from yuestudio.abc import edit as E
from yuestudio.abc._vendor import abc_tools as T
from yuestudio.abc.score import parse
from yuestudio.analysis import fit as F
from yuestudio.export import midi
from yuestudio.lyrics import syllables as S
from yuestudio.lyrics.doc import parse as parse_lyrics
from yuestudio.repair import apply_ops

SEEDS = range(6)


@pytest.fixture
def scores(compose, lyrics, faults):
    faults("simple")
    return [compose("Chinese, pop, 96 BPM", lyrics, s) for s in SEEDS]


def test_score_model_sections_and_phrases(scores):
    for abc in scores:
        sc = parse(abc)
        assert sc.bars and sc.sections and sc.vocal
        assert sum(len(s.bars) for s in sc.sections) == len(sc.bars)
        assert all(p.notes for p in sc.phrases())


@pytest.mark.parametrize("semis", [-5, -2, 1, 3, 6])
def test_transpose_round_trip(scores, semis):
    for abc in scores:
        up = E.transpose(abc, semis)
        a, b = T.parse(abc), T.parse(up)
        assert [n[1] + semis for n in a.voices["Vocal"].notes] == [n[1] for n in b.voices["Vocal"].notes]
        back = E.transpose(up, -semis)
        assert T.compare(a, T.parse(back))["match"]


@pytest.mark.parametrize("level", ["color", "rich", "jazz"])
def test_reharmonize_never_touches_melody_and_uses_dialect_chords(scores, level):
    for abc in scores:
        r = apply_ops(abc, [{"op": "reharmonize", "level": level}])
        assert r["ok"], r
        assert T.compare(T.parse(abc), T.parse(r["abc"]))["match"]
        for _, sym in parse(r["abc"]).chord_timeline():
            assert T.CHORD.fullmatch(sym), sym


def test_reharmonize_enriches_simple_harmony(scores, lyrics):
    from yuestudio.analysis.plan import analyze

    before = analyze(scores[0], lyrics)["harmony"]["unique"]
    after = analyze(apply_ops(scores[0], [{"op": "reharmonize", "level": "rich"}])["abc"], lyrics)["harmony"]["unique"]
    assert after > before


def test_set_chords_splits_notes_without_changing_them(scores):
    for abc in scores:
        out = E.set_bar_chords(abc, 5, [(Fraction(0), "Am7"), (Fraction(3, 2), "D7"), (Fraction(3), "G7sus4")])
        assert T.compare(T.parse(abc), T.parse(out))["match"]
        assert [s for _, s in parse(out).bars[5].chords] == ["Am7", "D7", "G7sus4"]


def test_tempo_structure_and_smoothing(scores):
    abc = scores[0]
    assert "Q:1/4=88" in E.set_tempo(abc, 88)
    n = len(parse(abc).sections)
    dup = apply_ops(abc, [{"op": "duplicate_section", "section": 2}])
    if dup["ok"]:
        assert len(parse(dup["abc"]).sections) == n + 1
    assert apply_ops(abc, [{"op": "smooth_endings"}])["ok"]
    assert not apply_ops(abc, [{"op": "nope"}])["ok"]


def test_display_has_lyrics_under_notes(scores, lyrics):
    sc = parse(scores[0])
    doc = parse_lyrics(lyrics)
    units = F.lyric_units(doc.expanded(), S.count)
    out = display.build(sc, units, {li.index: S.units(li.text) for li in doc.sung_lines}, "Title")
    assert "T:Title" in out and "w: 城 市" in out.replace("  ", " ")
    assert '"^' in out  # section labels


def test_midi_export(tmp_path, scores):
    path = tmp_path / "s.mid"
    midi(parse(scores[0]), str(path))
    data = path.read_bytes()
    assert data[:4] == b"MThd" and data.count(b"MTrk") == 4
