"""Hard gates first, then a transparent per-goal scorecard. Weights are deliberately
simple until the golden-set evaluation and team feedback calibrate them."""
from __future__ import annotations

GOALS = ("lyrics", "variety", "harmony", "singing")
WEIGHTS = {"lyrics": 0.35, "singing": 0.3, "variety": 0.2, "harmony": 0.15}


def take_card(plan_card: dict, length: dict, loop: dict | None, audio: dict, events: dict, asr: dict | None) -> dict:
    lyrics = plan_card.get("lyrics", 50.0)
    if asr and asr.get("available"):
        lyrics = 0.35 * lyrics + 0.65 * 100 * asr.get("coverage", 0.0)
        lyrics -= 15 * len(asr.get("skipped", [])) + 10 * len(asr.get("repeated", []))
    ratio = length.get("ratio", 1.0)
    if not length.get("ok", True):
        lyrics -= 25
    variety = plan_card.get("variety", 50.0) - (40 if loop else 0) - (20 if ratio > 1.25 else 0)
    n_lines = max(1, events.get("lines", 1))
    singing = plan_card.get("singing", 50.0) - 60 * len(events.get("a15", [])) / n_lines \
        - 60 * len(events.get("a16", [])) / n_lines
    harmony = plan_card.get("harmony", 50.0)
    card = {"lyrics": lyrics, "variety": variety, "harmony": harmony, "singing": singing}
    card = {k: round(max(0.0, min(100.0, v)), 1) for k, v in card.items()}
    penalty = 0.0
    if audio.get("clip_ratio", 0) > 0.001:
        penalty += 5
    if audio.get("abrupt_ending"):
        penalty += 4
    if audio.get("gaps"):
        penalty += 3 * len(audio["gaps"])
    total = sum(card[g] * w for g, w in WEIGHTS.items()) - penalty
    return {"card": card, "score": round(max(0.0, total), 1), "penalty": penalty}


def take_gates(length: dict, loop: dict | None, asr: dict | None) -> dict:
    gates = {"not_truncated": length.get("verdict") != "truncated", "length_ok": length.get("verdict") in ("ok",),
             "no_loop": loop is None}
    if asr and asr.get("instrumental"):
        gates["no_vocals_heard"] = asr.get("words_heard", 0) <= 8   # an instrumental must not sing words (A11)
    elif asr and asr.get("available"):
        gates["lyrics_heard"] = asr.get("coverage", 0) >= 0.6 and len(asr.get("skipped", [])) <= 1
    return gates
