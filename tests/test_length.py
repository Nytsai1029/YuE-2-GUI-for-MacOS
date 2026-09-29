"""Length target: lint, instrumental skeleton sizing, score fitting, exact trim."""
import numpy as np
import pytest
import soundfile as sf

from yuestudio.abc.score import parse
from yuestudio.analysis.plan import analyze
from yuestudio.audio.master import master
from yuestudio.lyrics.lint import LintContext, instrumental_skeleton, lint
from yuestudio.repair import fit_length


def test_lint_compares_lyrics_with_target(lyrics):
    rules = lambda t: {i["rule"] for i in lint(lyrics, LintContext(bpm=96, target_seconds=t))["issues"]}  # noqa: E731
    assert "lyrics.target_length" in rules(45)       # far too many lyrics for 0:45
    assert "lyrics.target_length" in rules(330)      # far too few for 5:30
    assert "lyrics.target_length" not in rules(None)


@pytest.mark.parametrize("target", [60, 180, 300])
def test_instrumental_skeleton_scales(target):
    out = lint("", LintContext(bpm=84, instrumental=True, target_seconds=target))
    assert abs(out["estimate"]["seconds"] - target) / target < 0.35


@pytest.mark.parametrize("target", [60, 150, 240])
def test_fit_length_instrumental_hits_target(compose, faults, target):
    faults("")
    abc = compose("cinematic, 84 BPM", instrumental_skeleton(120, 84), 2)
    new, info = fit_length(abc, target)
    assert abs(parse(new).seconds / target - 1) <= 0.08, info


def test_fit_length_never_cuts_lyrics(compose, faults, lyrics):
    faults("")
    abc = compose("pop, 96 BPM", lyrics, 4)
    for target in (40, 200):
        new, info = fit_length(abc, target)
        a = analyze(new, lyrics, target_seconds=target)
        assert a["gates"]["no_missing_lyrics"]
        assert parse(new).bpm in range(int(parse(abc).bpm * 0.93), int(parse(abc).bpm * 1.07) + 1)
        assert sum(s["op"] == "duplicate_section" for s in info["steps"]) <= 2
    assert analyze(abc, lyrics, target_seconds=40)["length"]["penalty"] > 0


def test_exact_length_trim(tmp_path):
    sr = 48000
    x = (0.2 * np.sin(2 * np.pi * 220 * np.arange(sr * 20) / sr)).astype(np.float32)
    sf.write(tmp_path / "a.flac", np.stack([x, x], 1), sr)
    info = master(str(tmp_path / "a.flac"), str(tmp_path / "b.flac"), max_seconds=12)
    y, _ = sf.read(tmp_path / "b.flac")
    assert info["trimmed_to_target"] and abs(len(y) / sr - 12) < 0.01 and abs(y[-10:]).max() < 1e-3
