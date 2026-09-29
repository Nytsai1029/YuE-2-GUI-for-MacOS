"""Worker contract (via the fake engine) and the HTTP API end to end."""
import time

import pytest
from fastapi.testclient import TestClient

from yuestudio.config import DEFAULT_SETTINGS, deep_merge
from yuestudio.engine import Engine
from yuestudio.engine.rpc import WorkerError


@pytest.fixture
def engine(tmp_path):
    settings = deep_merge(DEFAULT_SETTINGS, {"engine": {"mode": "fake"}})
    eng = Engine(tmp_path, lambda: settings)
    yield eng
    eng.shutdown()


def test_full_stage_protocol(engine, tmp_path, lyrics):
    engine.ensure_loaded()
    assert engine.caps["fake"] and engine.caps["nar_progress"]
    p = engine.call("plan", {"out_dir": str(tmp_path / "p"), "style": "pop, 96 BPM", "lyrics": lyrics, "seed": 3})
    chunks = []
    s = engine.call("semantic", {"out_dir": str(tmp_path / "c"), "plan_dir": p["plan_dir"], "seed": 9},
                    on_event=lambda m: chunks.append(len(m.get("chunk", []))) if m.get("ev") == "tokens" else None)
    assert sum(chunks) == s["n_tokens"] > 0
    progress = []
    r = engine.call("render", {"out_dir": str(tmp_path / "c"), "plan_dir": p["plan_dir"], "tokens_path": s["tokens_path"],
                               "seed": 9, "ode_steps": 8, "noise_seed": 9}, on_event=progress.append)
    assert r["seconds"] > 10 and any(m.get("phase") == "nar" for m in progress)


def test_stdout_noise_cannot_corrupt_protocol(engine, tmp_path, lyrics, faults):
    faults("stdout_noise")
    r = engine.call("plan", {"out_dir": str(tmp_path / "p"), "style": "pop", "lyrics": lyrics, "seed": 1})
    assert r["abc"].startswith("X:1")


def test_crash_is_recovered_by_restart(engine, tmp_path, lyrics, monkeypatch):
    engine.ensure_loaded()
    p = engine.call("plan", {"out_dir": str(tmp_path / "p"), "style": "pop", "lyrics": lyrics, "seed": 1})
    s = engine.call("semantic", {"out_dir": str(tmp_path / "c"), "plan_dir": p["plan_dir"], "seed": 2})
    monkeypatch.setenv("YUESTUDIO_FAKE_CRASH_ONCE", str(tmp_path / "crashed"))
    engine.restart()  # new worker inherits the fault
    r = engine.call("render", {"out_dir": str(tmp_path / "c"), "plan_dir": p["plan_dir"],
                               "tokens_path": s["tokens_path"], "seed": 2, "ode_steps": 4})
    assert (tmp_path / "crashed").exists() and r["seconds"] > 0 and engine.restarts >= 2


def test_memory_error_is_classified(engine, tmp_path, lyrics, faults):
    faults("oom_semantic")
    p = engine.call("plan", {"out_dir": str(tmp_path / "p"), "style": "pop", "lyrics": lyrics, "seed": 1})
    with pytest.raises(WorkerError) as err:
        engine.call("semantic", {"out_dir": str(tmp_path / "c"), "plan_dir": p["plan_dir"], "seed": 2})
    assert err.value.code == "OOM"


def test_bad_abc_rejected_by_engine_parser(engine):
    assert engine.call("abc_check", {"abc": "X:1\nT:\nnope"})["ok"] is False


# --------------------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path):
    from yuestudio.app import create_app

    with TestClient(create_app(tmp_path, fake=True)) as c:
        yield c


def test_api_take_end_to_end(client, lyrics):
    song = client.post("/api/songs", json={"title": "Test"}).json()
    blocked = client.post(f"/api/songs/{song['id']}/takes", json={"lyrics": "", "fields": {}, "preset": "draft"})
    assert blocked.status_code == 422
    r = client.post(f"/api/songs/{song['id']}/takes", json={"lyrics": lyrics, "fields": {"bpm": 96}, "preset": "draft"})
    take_id = r.json()["take"]["id"]
    for _ in range(120):
        t = client.get(f"/api/takes/{take_id}").json()
        if t["status"] in ("done", "failed"):
            break
        time.sleep(0.25)
    assert t["status"] == "done", t.get("error")
    final = [c for c in t["candidates"] if c["stage"] == "final"][0]
    assert {"master", "lrc", "abc", "midi", "recipe"} <= set(final["files"])
    assert client.get(final["files"]["master"]).status_code == 200
    plan = t["plans"][0]
    assert "w:" in client.get(f"/api/plans/{plan['id']}/display").json()["abc"]
    notes = client.get(f"/api/plans/{plan['id']}/notes").json()
    assert notes["vocal"] and notes["chords"]
    rep = client.post(f"/api/plans/{plan['id']}/repair", json={"ops": [{"op": "reharmonize", "level": "rich"}]}).json()
    assert rep["plan"]["source"] == "edited" and rep["plan"]["parent_id"] == plan["id"]


def test_api_instrumental(client):
    song = client.post("/api/songs", json={"title": "Piano"}).json()
    r = client.post(f"/api/songs/{song['id']}/takes", json={"lyrics": "", "fields": {"gender": "none", "bpm": 84},
                                                            "preset": "draft"})
    assert r.status_code == 200


def test_security_guards(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 421
    assert client.post("/api/songs", json={}, headers={"origin": "http://evil.example"}).status_code == 403
    assert client.get("/api/health").status_code == 200
