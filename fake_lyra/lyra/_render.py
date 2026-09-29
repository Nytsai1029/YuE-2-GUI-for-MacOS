"""Toy "decoder" for the fake engine: renders the planned ABC to audible audio.

Vocal notes become a vibrato tone, chords a pad, plus bass and a simple beat. With
YUESTUDIO_FAKE_TTS=1 each lyric line is also spoken by macOS `say` at its phrase so
ASR/alignment can be exercised end to end on a laptop.

Audio faults (YUESTUDIO_FAKE_FAULTS): shout (A15 phrase-end blow-up), hum (A16:
a line keeps its melody but loses its words).
"""
from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction

import numpy as np

from ._composer import faults, parse_lyrics
from .music_tools.abc_tools import parse

SR = 48000
NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def chord_pitches(symbol):
    m = re.match(r"([A-G])(#|b)?(m(?!aj))?", symbol)
    if not m:
        return []
    root = 48 + NOTE_NAMES[m.group(1)] + {"#": 1, "b": -1, None: 0}[m.group(2)]
    third = 3 if m.group(3) else 4
    return [root, root + third, root + 7]


def phrases(notes, gap_q=Fraction(1)):
    """Split vocal notes into phrases at rests of >= 1 quarter."""
    out, cur, end = [], [], None
    for onset, pitch, dur in notes:
        if cur and onset - end >= gap_q:
            out.append(cur)
            cur = []
        cur.append((onset, pitch, dur))
        end = onset + dur
    if cur:
        out.append(cur)
    return out


def say(text, voice, path):
    subprocess.run(["say", "-v", voice, "-o", path, "--data-format=LEI16@48000", text],
                   check=True, capture_output=True, timeout=60)


def render(abc, lyrics, n_samples, seed):
    rng = random.Random(seed)
    active = faults()
    score = parse(abc)
    spq = 60.0 / score.bpm  # seconds per quarter
    out = np.zeros((n_samples, 2), dtype=np.float32)

    def add(start_s, sig, pan=0.0):
        a = int(start_s * SR)
        if a >= n_samples or a < 0:
            return
        b = min(n_samples, a + len(sig))
        seg = sig[: b - a]
        out[a:b, 0] += seg * (1 - pan) * 0.5 * 2
        out[a:b, 1] += seg * (1 + pan) * 0.5 * 2

    def tone(freq, dur_s, amp, harmonics=(1, .5, .25), vibrato=0.0, attack=0.02, release=0.08):
        n = max(1, int(dur_s * SR))
        t = np.arange(n) / SR
        phase = 2 * np.pi * freq * t + (vibrato * np.sin(2 * np.pi * 5.5 * t) if vibrato else 0)
        sig = sum(h * np.sin(k * phase) for k, h in enumerate(harmonics, start=1))
        env = np.minimum(1, t / attack) * np.minimum(1, (dur_s - t) / release).clip(0, 1)
        return (amp * sig * env).astype(np.float32)

    vocal = score.voices["Vocal"]
    ins = score.voices["Ins"]
    vocal_phrases = phrases(vocal.notes)
    shout_phrases = set()
    for i, _ in enumerate(vocal_phrases):
        if "shout" in active and rng.random() < active["shout"] * 0.5:
            shout_phrases.add(i)
    for pi, ph in enumerate(vocal_phrases):
        for ni, (onset, pitch, dur) in enumerate(ph):
            amp = 0.10
            harm = (1, .5, .25)
            if pi in shout_phrases and ni >= len(ph) - 2:
                amp, harm = 0.32, (1, .9, .8, .7, .6, .5)
                pitch += 5
            add(float(onset) * spq, tone(midi_hz(pitch), float(dur) * spq, amp, harm, vibrato=0.6), 0.0)
        if pi in shout_phrases:
            end_s = float(ph[-1][0] + ph[-1][2]) * spq
            burst = np.concatenate([tone(midi_hz(76 + (k * 3) % 12), 0.06, 0.12) for k in range(20)])
            add(end_s, burst, 0.3)
    for onset, pitch, dur in ins.notes:
        add(float(onset) * spq, tone(midi_hz(pitch), float(dur) * spq, 0.06, (1, .3), release=0.2), -0.4)
    chords = vocal.chords + [(vocal.time, None)]
    for (start, sym), (end, _) in zip(chords, chords[1:]):
        dur_s = float(end - start) * spq
        for p in chord_pitches(sym):
            add(float(start) * spq, tone(midi_hz(p), dur_s, 0.025, (1, .2), attack=0.2, release=0.3), 0.2)
        bass = chord_pitches(sym)[:1]
        if bass:
            beats = int(float(end - start))
            for b in range(beats):
                add((float(start) + b) * spq, tone(midi_hz(bass[0] - 12), spq * 0.9, 0.08, (1, .4)), 0)
    total_beats = int(float(vocal.time))
    kick = (np.sin(2 * np.pi * np.cumsum(np.linspace(120, 45, int(0.18 * SR))) / SR)
            * np.exp(-np.linspace(0, 8, int(0.18 * SR)))).astype(np.float32) * 0.25
    hat = (np.random.default_rng(seed).standard_normal(int(0.03 * SR)) * np.exp(-np.linspace(0, 9, int(0.03 * SR)))
           ).astype(np.float32) * 0.03
    for b in range(total_beats):
        if b % 2 == 0:
            add(b * spq, kick)
        add(b * spq, hat, 0.5)
        add((b + 0.5) * spq, hat, -0.5)

    if os.environ.get("YUESTUDIO_FAKE_TTS") == "1" and shutil.which("say"):
        _speak_lines(out, lyrics, vocal_phrases, spq, active, rng, add)
    peak = float(np.abs(out).max()) or 1.0
    if peak > 0.95:
        out *= 0.95 / peak
    return out


def _speak_lines(out, lyrics, vocal_phrases, spq, active, rng, add):
    lines = [(s["tag"], line) for s in parse_lyrics(lyrics) for line in s["lines"]]
    with tempfile.TemporaryDirectory() as tmp:
        for i, ph in enumerate(vocal_phrases):
            if i >= len(lines):
                break
            _, text = lines[i]
            if "hum" in active and rng.random() < active["hum"] * 0.4:
                continue  # melody plays, words never arrive: "voiced but wordless"
            voice = "Tingting" if re.search(r"[一-鿿]", text) else "Samantha"
            path = os.path.join(tmp, f"{i}.aiff")
            try:
                say(text, voice, path)
                import soundfile as sf

                speech, sr = sf.read(path, dtype="float32")
                if speech.ndim > 1:
                    speech = speech.mean(axis=1)
                start = float(ph[0][0]) * spq
                span = float(ph[-1][0] + ph[-1][2] - ph[0][0]) * spq
                if len(speech) / SR > span * 1.3 and span > 0.5:
                    idx = np.linspace(0, len(speech) - 1, int(span * 1.2 * SR)).astype(int)
                    speech = speech[idx]
                add(start, speech * 0.8, 0.0)
            except Exception:
                continue
