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


def test_instrumentalize_moves_vocal_line_to_instrument(compose, faults):
    from yuestudio.abc._vendor import abc_tools as T
    from yuestudio.abc.score import parse as parse_score
    from yuestudio.repair import apply_ops

    faults("vocal_in_instrumental")
    skeleton = "[Intro]\n\n[Interlude]\n\n[Interlude]\n\n[Outro]\n"
    for seed in range(6):
        abc = compose("cinematic, instrumental, no vocals", skeleton, seed)
        before = parse_score(abc)
        assert before.vocal  # reproduces the bug: the model writes a singer's line anyway
        r = apply_ops(abc, [{"op": "instrumentalize"}])
        assert r["ok"], r
        after = parse_score(r["abc"])
        assert not after.vocal
        assert [s for _, s in after.chord_timeline()] == [s for _, s in before.chord_timeline()]
        info = r["applied"][0]
        assert info["moved_to_instrument"] > 0 and info["moved_to_instrument"] + info["silenced"] == len(before.vocal)
        T.parse(r["abc"])
        assert analyze(r["abc"], "", instrumental=True)["gates"]["no_vocal_melody"]
    # vocal songs work too (both voices busy): everything is silenced or moved, still valid
    faults("")
    song = compose("pop", "[Verse]\nhello there my friend\nwe sing along tonight\n", 1)
    assert not parse_score(apply_ops(song, [{"op": "instrumentalize"}])["abc"]).vocal


def test_director_auto_instrumentalizes(tmp_path, faults, monkeypatch):
    import threading

    from yuestudio import service
    from yuestudio.db import DB
    from yuestudio.director.pipeline import Director
    from yuestudio.engine import Engine
    from yuestudio.jobs.bus import Bus

    faults("vocal_in_instrumental")
    db = DB(tmp_path / "s.db")
    db.save_settings({"engine": {"mode": "fake"}})
    eng = Engine(tmp_path, db.settings)
    try:
        d = Director(db, eng, Bus(), tmp_path, db.settings, None)
        song = service.create_song(db, "Piano")
        draft = service.create_draft(db, song["id"], "", {"gender": "none", "bpm": 84})
        take = service.create_take(db, song["id"], draft["id"], "draft")
        d.run_take(take["id"], threading.Event())
        plan = db.one("SELECT * FROM plans WHERE take_id=?", (take["id"],))
        assert plan["edit_ops"] and plan["edit_ops"][0]["op"] == "instrumentalize"
        assert plan["analysis"]["gates"]["no_vocal_melody"]
        assert db.get("takes", take["id"])["status"] == "done"
    finally:
        eng.shutdown()


@pytest.mark.parametrize("gender", ["female", "male"])
def test_range_report(compose, lyrics, faults, gender):
    faults("")
    r = analyze(compose("pop", lyrics, 1), lyrics, gender=gender)
    assert r["range"]["available"] and r["range"]["low"] <= r["range"]["high"]
