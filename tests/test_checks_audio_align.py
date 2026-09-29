"""Token gates, audio metrics/events, mastering and ASR alignment on synthetic data."""
import random

import numpy as np
import soundfile as sf

from yuestudio.align import coverage
from yuestudio.audio.features import extract
from yuestudio.audio.master import master
from yuestudio.audio.metrics import hum_events, integrated_lufs, phrase_events
from yuestudio.checks.semantic import LoopDetector, length_gate

SR = 48000


# --------------------------------------------------------------------------- token gates
def test_loop_detector_finds_stuck_loops_only():
    rng = random.Random(1)
    song = [rng.randrange(32768) for _ in range(1500)]
    span = song[600:800]
    stuck = song[:800] + span * 3 + song[800:]
    assert LoopDetector().feed(stuck) is not None
    # a musical repeat (chorus twice) is never token-exact
    noisy = song[:800] + [t if rng.random() > 0.1 else rng.randrange(32768) for t in span] + song[800:]
    assert LoopDetector().feed(noisy) is None
    assert LoopDetector().feed(song) is None


def test_length_gate():
    assert length_gate(4500, 180, False)["verdict"] == "ok"
    assert length_gate(3000, 180, False)["verdict"] == "short"      # sections skipped (A1)
    assert length_gate(6000, 180, False)["verdict"] == "long"       # extra sections (A17)
    assert length_gate(9000, 180, True)["verdict"] == "truncated"


# --------------------------------------------------------------------------- loudness & mastering
def test_lufs_reference_and_master_hits_target(tmp_path):
    t = np.arange(SR * 10) / SR
    tone = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    stereo = np.stack([tone, tone], 1)
    assert abs(integrated_lufs(stereo, SR) - (-6.0)) < 0.5
    src, dst = tmp_path / "in.flac", tmp_path / "out.flac"
    sf.write(src, stereo * 0.1, SR)
    info = master(str(src), str(dst), lufs=-14, true_peak=-1)
    assert abs(info["output_lufs"] + 14) < 0.6 and info["true_peak_db"] <= -0.9


# --------------------------------------------------------------------------- A15 / A16 detectors
def _song(tmp_path, shout=False, hum=False):
    rng = np.random.default_rng(0)
    n = SR * 12
    x = np.zeros(n, np.float32)
    t = np.arange(n) / SR
    voice = 0.08 * (np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 440 * t))
    x += voice.astype(np.float32)
    x += (rng.standard_normal(n) * 0.005).astype(np.float32)
    if shout:  # line 1 ends 2.5..3.5 s: louder, brighter, then a burst of clicks
        a, b = int(2.5 * SR), int(3.5 * SR)
        x[a:b] += (0.3 * np.sign(np.sin(2 * np.pi * 440 * t[a:b]))).astype(np.float32)
        for k in range(14):
            c = int((3.5 + k * 0.09) * SR)
            x[c:c + 300] += (rng.standard_normal(300) * 0.4).astype(np.float32)
    path = tmp_path / ("shout.flac" if shout else "calm.flac")
    sf.write(path, np.stack([x, x], 1), SR)
    return str(path)


def test_phrase_end_blowup_detected(tmp_path):
    lines = [{"line": 0, "start": 0.5, "end": 3.5}, {"line": 1, "start": 6.0, "end": 9.0}]
    assert phrase_events(extract(_song(tmp_path, shout=True)), lines)
    assert not phrase_events(extract(_song(tmp_path)), lines)


def test_humming_detected_when_voiced_but_no_words(tmp_path):
    f = extract(_song(tmp_path))
    lines = [{"line": 0, "start": 1.0, "end": 4.0}, {"line": 1, "start": 6.0, "end": 9.0}]
    words = [{"text": "hello", "start": 1.0, "end": 4.0}]
    events = hum_events(f, lines, words)
    assert [e["line"] for e in events] == [1]


# --------------------------------------------------------------------------- ASR alignment
def test_asr_alignment_finds_drops_repeats_and_order():
    lines = [{"line": 0, "text": "城市的灯火 慢慢亮起来"}, {"line": 1, "text": "我走在雨里 想起了你"},
             {"line": 2, "text": "every window glowing just for you"}]
    t = 0.0
    words = []
    for text in ["城市的灯火慢慢亮起来", "every window glowing just for you", "every window glowing just for you"]:
        for tok in (list(text) if "城" in text else text.split()):
            words.append({"text": tok, "start": t, "end": t + 0.3})
            t += 0.3
    r = coverage(lines, words)
    assert r["skipped"] == [1]                       # line 2 never sung (A1)
    assert r["repeated"] and r["repeated"][0]["line"] == 2   # sung twice (A17)
    assert r["lines"][0]["coverage"] == 1.0
    homophones = coverage([{"line": 0, "text": "在这里"}], [{"text": "再这里", "start": 0, "end": 1}])
    assert homophones["coverage"] == 1.0             # toneless pinyin ignores homophone choices
