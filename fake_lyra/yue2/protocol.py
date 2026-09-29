"""Fake of upstream yue2.protocol: same names and shapes, no model."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

EOD = 151643
ABC_START, ABC_END = 151847, 151848
MUSIC_START, MUSIC_END = 151851, 151852
CODEC_OFFSET, CODEC_SIZE = 151853, 32768
CONTEXT = 24576
PROTOCOL_VERSION = "yue2-native-v1"
INSTRUCTIONS = {
    "off": "Generate music with codec tokens from the given conditions.",
    "melody": "Generate a melody-only ABC transcription without chord symbols, then generate music with codec tokens from the given conditions.",
    "full": "Generate a chord-annotated ABC transcription, then generate music with codec tokens from the given conditions.",
}


@dataclass(frozen=True)
class Sampling:
    temperature: float = 1.0
    top_p: float = 0.95
    top_k: int = 100
    repetition_penalty: float = 1.2
    penalty_window: int = 50
    min_tokens: int = 200
    max_tokens: int = 9000


@dataclass(frozen=True)
class GenerationConfig:
    abc: Sampling = field(default_factory=lambda: Sampling(.7, .9, 30, 1.005, 100, 32, 4096))
    semantic: Sampling = field(default_factory=Sampling)
    ode_steps: int = 32
    ode_method: str = "midpoint"
    context: int = CONTEXT
    version: str = PROTOCOL_VERSION


def resolve_sampling(value, default):
    if value is None:
        return default
    if isinstance(value, Sampling):
        return value
    return Sampling(**{**asdict(default), **value})


@dataclass(frozen=True)
class SongRequest:
    style: str
    lyrics: str
    cot: str = "full"
    seed: int = 831001
    abc: str | None = None
    cfg_scale: float | None = None
    id: str = "song"

    def __post_init__(self):
        if self.cot not in INSTRUCTIONS:
            raise ValueError("cot must be off, melody or full")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("seed must be an integer in [0, 2**63)")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,179}", self.id):
            raise ValueError("id must be a filename-safe identifier")
        if self.abc is not None and (self.cot == "off" or not self.abc.strip()):
            raise ValueError("External ABC requires nonempty text and cot=melody/full")
        if self.cfg_scale is not None and (not math.isfinite(self.cfg_scale) or not 0 <= self.cfg_scale <= 20):
            raise ValueError("cfg_scale must be finite and in [0,20]")

    @property
    def guidance(self):
        return (1.01 if self.cot == "off" else 1.0) if self.cfg_scale is None else self.cfg_scale

    def text(self):
        return f"{INSTRUCTIONS[self.cot]}\n[Tags]\n{self.style}\n[Lyrics]\n{self.lyrics}\n"

    def to_dict(self):
        return asdict(self)


class FakeTokenizer:
    """Reversible toy tokenizer: one id per character (ids stay below EOD)."""

    def encode(self, text):
        return [min(ord(c), EOD - 1) for c in text]

    def decode(self, ids):
        return "".join(chr(i) for i in ids)


def token_prefixes(request, tokenizer, abc_ids=None):
    base = [EOD] + tokenizer.encode(request.text())
    if request.cot == "off":
        return base + [ABC_START, ABC_END, MUSIC_START]
    if abc_ids is None:
        if request.abc is None:
            return base + [ABC_START]
        abc_ids = tokenizer.encode(request.abc)
    return base + [ABC_START] + list(abc_ids) + [ABC_END, MUSIC_START]
