"""Fake of upstream yue2.pipeline data classes (same persistence format)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .protocol import SongRequest


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class SymbolicPlan:
    request: SongRequest
    abc: str | None
    abc_ids: list
    prefix: list
    timing: dict = field(default_factory=dict)
    truncated: bool = False

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        if self.abc is not None:
            (directory / "score.abc").write_bytes(self.abc.encode("utf-8"))
        np.save(directory / "abc_tokens.npy", np.asarray(self.abc_ids, dtype=np.int32))
        np.save(directory / "prefix.npy", np.asarray(self.prefix, dtype=np.int32))
        (directory / "plan.json").write_text(json.dumps(
            {"request": self.request.to_dict(), "timing": self.timing, "truncated": self.truncated,
             "prefix": self.prefix, "abc_ids": self.abc_ids, "abc": self.abc}, ensure_ascii=False))
        names = ["plan.json", "abc_tokens.npy", "prefix.npy"] + (["score.abc"] if self.abc is not None else [])
        (directory / "plan_manifest.json").write_text(json.dumps({n: _sha(directory / n) for n in names}))

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        hashes = json.loads((directory / "plan_manifest.json").read_text())
        for name, digest in hashes.items():
            if _sha(directory / name) != digest:
                raise ValueError("Saved plan changed; supply modified ABC as an external planner input")
        data = json.loads((directory / "plan.json").read_text())
        return cls(SongRequest(**data["request"]), data["abc"], data["abc_ids"], data["prefix"],
                   data["timing"], data["truncated"])


@dataclass
class SemanticResult:
    plan: SymbolicPlan
    tokens: list
    timing: dict
    truncated: bool
