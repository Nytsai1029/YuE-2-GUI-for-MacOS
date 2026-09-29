"""Token-stage gates (run before the expensive acoustic stage).

* LoopDetector watches semantic tokens as they stream and reports a stuck loop: a
  segment of P tokens repeated back to back until the repetition covers
  >= max(2P, 12 s). Real musical repeats (a chorus sung twice) are never token-exact;
  autoregressive loops are.
* length_gate compares the take's length with the plan's predicted duration: too
  short means sections were skipped (A1); too long means extra sections or loops (A17).
"""
from __future__ import annotations

from dataclasses import dataclass

FRAME = 0.04


@dataclass
class Loop:
    period: int
    start: int
    length: int

    def to_dict(self):
        return {"period": self.period, "start": self.start, "length": self.length,
                "period_s": self.period * FRAME, "start_s": self.start * FRAME, "length_s": self.length * FRAME}


class LoopDetector:
    def __init__(self, n: int = 24, min_period: int = 25, max_period: int = 1500, min_span: int = 300):
        self.n, self.min_period, self.max_period, self.min_span = n, min_period, max_period, min_span
        self.tokens: list[int] = []
        self.seen: dict[tuple, list[int]] = {}
        self.runs: dict[int, int] = {}
        self.found: Loop | None = None

    def feed(self, chunk: list[int]) -> Loop | None:
        for tok in chunk:
            self.tokens.append(int(tok))
            i = len(self.tokens) - 1
            # extend runs for tracked periods
            for p in list(self.runs):
                if i - p >= 0 and self.tokens[i] == self.tokens[i - p]:
                    self.runs[p] += 1
                    if self.found is None and self.runs[p] >= max(2 * p, self.min_span):
                        self.found = Loop(p, i - self.runs[p] - p + 1, self.runs[p] + p)
                else:
                    del self.runs[p]
            if i + 1 >= self.n:
                key = tuple(self.tokens[i + 1 - self.n:i + 1])
                prev = self.seen.setdefault(key, [])
                for j in prev[-4:]:
                    p = i - j
                    if self.min_period <= p <= self.max_period and p not in self.runs:
                        self.runs[p] = self.n
                prev.append(i)
        return self.found


def detect_loop(tokens: list[int], **kwargs) -> Loop | None:
    d = LoopDetector(**kwargs)
    return d.feed(tokens)


def length_gate(n_tokens: int, predicted_seconds: float, truncated: bool) -> dict:
    seconds = n_tokens * FRAME
    ratio = seconds / predicted_seconds if predicted_seconds else 1.0
    verdict = "ok"
    if truncated:
        verdict = "truncated"
    elif ratio < 0.8:
        verdict = "short"
    elif ratio > 1.25:
        verdict = "long"
    return {"seconds": round(seconds, 2), "predicted": round(predicted_seconds, 2), "ratio": round(ratio, 3),
            "verdict": verdict, "ok": verdict == "ok"}
