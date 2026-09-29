"""Fault matrix: each injected failure mode must be caught at the plan stage."""
import pytest

from yuestudio.analysis.plan import analyze

SEEDS = range(8)


def run(compose, lyrics, faults, spec):
    faults(spec)
    return [analyze(compose("Chinese, pop, 96 BPM", lyrics, s), lyrics) for s in SEEDS]


def hits(results, rule):
    return sum(rule in {i["rule"] for i in r["issues"]} for r in results)


def test_clean_plans_pass_gates(compose, lyrics, faults):
    results = run(compose, lyrics, faults, "")
    assert all(r["passed"] for r in results)


def test_repeated_section_is_extra_and_fails_gate(compose, lyrics, faults):  # A17
    results = run(compose, lyrics, faults, "repeat_section")
    assert hits(results, "plan.extra_section") == len(SEEDS)
    assert not any(r["passed"] for r in results)


def test_skipped_section_predicts_lyric_loss(compose, lyrics, faults):  # A1
    results = run(compose, lyrics, faults, "skip_section")
    assert hits(results, "plan.cram") + hits(results, "plan.missing_lyrics") >= len(SEEDS) - 1


def test_cram_and_melisma(compose, lyrics, faults):  # A6 / A16
    assert hits(run(compose, lyrics, faults, "cram:0.5"), "plan.cram") == len(SEEDS)
    assert hits(run(compose, lyrics, faults, "melisma:0.6"), "plan.melisma") >= len(SEEDS) - 1


def test_leap_endings_flagged(compose, lyrics, faults):  # A15
    assert hits(run(compose, lyrics, faults, "leap_end"), "plan.phrase_end") == len(SEEDS)


def test_loop_and_simple_chords(compose, lyrics, faults):  # B1 / B3
    assert hits(run(compose, lyrics, faults, "loop"), "plan.loop") == len(SEEDS)
    assert hits(run(compose, lyrics, faults, "simple"), "plan.simple_chords") == len(SEEDS)


def test_unreadable_score():
    r = analyze("X:1\nT:\nnot abc", "[Verse]\nhello\n")
    assert r["ok"] is False and r["gates"]["parse"] is False


def test_instrumental_gate(compose, faults):
    faults("")
    abc = compose("cinematic, instrumental", "[Intro]\n\n[Interlude]\n\n[Outro]\n", 3)
    r = analyze(abc, "", instrumental=True)
    assert r["gates"]["no_vocal_melody"]
    vocal = compose("pop", "[Verse]\nhello there my friend\n", 3)
    r2 = analyze(vocal, "", instrumental=True)
    assert not r2["gates"]["no_vocal_melody"]
    assert "plan.vocal_in_instrumental" in {i["rule"] for i in r2["issues"]}


@pytest.mark.parametrize("gender", ["female", "male"])
def test_range_report(compose, lyrics, faults, gender):
    faults("")
    r = analyze(compose("pop", lyrics, 1), lyrics, gender=gender)
    assert r["range"]["available"] and r["range"]["low"] <= r["range"]["high"]
