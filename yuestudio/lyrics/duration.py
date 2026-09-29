"""Duration and token-budget estimates before anything is generated.

Constants are deliberately conservative and live in one place so the M0 probe /
calibration can refine them with measurements from the user's own engine.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

FRAME_SECONDS = 0.04               # one semantic token per 40 ms
SEMANTIC_MAX = 9000                # upstream default semantic budget (~360 s)
ABC_MAX_DEFAULT = 4096
CONTEXT = 24576
COMFORT_SECONDS = 300              # the model is documented for songs up to ~5 min
SYLLABLES_PER_BEAT = 1.5           # typical pop delivery
BREATH_BEATS = 1.0
INSTRUMENTAL_BEATS = {"intro": 16, "interlude": 16, "outro": 16}
ABC_TOKENS_PER_BAR = 44.0          # refined by calibration (probe measures real tokens/bar)
ABC_TOKENS_OVERHEAD = 90
PROMPT_CHARS_PER_TOKEN = 2.2       # rough for mixed zh/en text with the Qwen tokenizer


@dataclass
class Estimate:
    seconds: float
    beats: float
    bars: int
    semantic_tokens: int
    abc_tokens: int
    prompt_tokens: int
    sections: list[dict]

    def to_dict(self):
        return self.__dict__


def line_beats(syllables: int) -> float:
    beats = syllables / SYLLABLES_PER_BEAT + BREATH_BEATS
    return max(4.0, math.ceil(beats / 4.0) * 4.0)   # lines land on whole bars


def estimate(doc, bpm: float = 96.0, sung_text: str | None = None, style: str = "",
             abc_tokens_per_bar: float = ABC_TOKENS_PER_BAR, edm: bool = False,
             drum_ratio: float = 1.0, instrumental: bool = False) -> Estimate:
    """``bpm`` is the vocal-feel tempo (half of the drum tempo for fast EDM). EDM drops and
    breaks run about twice as long as pop instrumental passages."""
    bpm = max(40.0, min(220.0, float(bpm or 96)))
    total_beats = 0.0
    sections = []
    for s in doc.expanded():
        if s.lines:
            beats = sum(line_beats(line.syllables) for line in s.lines)
        else:
            beats = INSTRUMENTAL_BEATS.get(s.kind, 8) * (2 if edm and s.kind != "outro" else 1)
            if instrumental and s.kind != "outro":
                beats *= 2  # a whole instrumental piece: each section carries the music on its own
        total_beats += beats
        sections.append({"tag": s.tag or "Verse", "lines": len(s.lines), "beats": beats,
                         "seconds": beats * 60.0 / bpm})
    seconds = total_beats * 60.0 / bpm
    bars = int(math.ceil(total_beats * drum_ratio / 4.0))  # the score is written at the drum tempo
    text_len = len(sung_text or doc.text) + len(style) + 160
    return Estimate(seconds=seconds, beats=total_beats, bars=bars,
                    semantic_tokens=int(seconds / FRAME_SECONDS),
                    abc_tokens=int(bars * abc_tokens_per_bar + ABC_TOKENS_OVERHEAD),
                    prompt_tokens=int(text_len / PROMPT_CHARS_PER_TOKEN),
                    sections=sections)


def budgets(est: Estimate, predicted_seconds: float | None = None) -> dict:
    """Size max_tokens for both AR phases from the estimate (plan-level prediction wins)."""
    seconds = predicted_seconds or est.seconds
    abc_max = max(ABC_MAX_DEFAULT, int(est.abc_tokens * 1.35))
    semantic_max = min(SEMANTIC_MAX, max(600, int(seconds * 1.2 / FRAME_SECONDS)))
    semantic_min = max(200, int(seconds * 0.8 / FRAME_SECONDS)) if predicted_seconds else 200
    room = CONTEXT - est.prompt_tokens - 8
    abc_max = min(abc_max, room - 1)
    return {"abc_max_tokens": abc_max, "semantic_max_tokens": semantic_max,
            "semantic_min_tokens": min(semantic_min, semantic_max - 1),
            "context_ok": est.prompt_tokens + est.abc_tokens + semantic_max < CONTEXT}
