"""The failure-mode catalog: one registry for every check the harness runs.

A rule declares *what* it guards against (catalog id such as ``A6``), *when* it runs
(``stage``), how bad a hit is by default, which of the four goals it feeds, and a
bilingual title. Its ``check`` function yields :class:`Issue` objects. Adding a rule
never requires touching the pipeline: import the module that defines it.

Stages:  pre   - lyrics/style lint before anything is generated (instant)
         plan  - analysis of a generated ABC score (seconds, before audio)
         tok   - semantic-token checks (before the expensive acoustic stage)
         audio - rendered audio + ASR
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

STAGES = ("pre", "plan", "tok", "audio")
SEVERITIES = ("error", "warn", "hint")
GOALS = ("lyrics", "variety", "harmony", "singing", "audio", "workflow")


@dataclass
class Fix:
    """A machine-applicable repair. ``lines`` maps editor line index -> replacement text
    (``None`` deletes the line); ``doc`` replaces the whole document."""

    label: dict[str, str]
    lines: dict[int, str | None] | None = None
    doc: str | None = None

    def to_dict(self):
        out = {"label": self.label}
        if self.lines is not None:
            out["lines"] = {str(k): v for k, v in self.lines.items()}
        if self.doc is not None:
            out["doc"] = self.doc
        return out


@dataclass
class Issue:
    rule: str
    catalog: str
    severity: str
    goal: str
    message: dict[str, str]
    line: int | None = None          # editor line index (0-based) when the issue is textual
    start: int | None = None         # column range inside that line
    end: int | None = None
    section: int | None = None       # section index (lyrics/ABC) when relevant
    time: tuple[float, float] | None = None  # seconds range for audio issues
    fix: Fix | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        out = {k: v for k, v in asdict(self).items() if v is not None and k != "fix"}
        if self.fix is not None:
            out["fix"] = self.fix.to_dict()
        return out


@dataclass
class Rule:
    id: str
    catalog: str
    stage: str
    severity: str
    goal: str
    title: dict[str, str]
    check: Callable[..., Iterable[Issue]]
    doc: str = ""

    def issue(self, message_en: str, message_zh: str, **kwargs) -> Issue:
        severity = kwargs.pop("severity", self.severity)
        return Issue(rule=self.id, catalog=self.catalog, severity=severity, goal=self.goal,
                     message={"en": message_en, "zh": message_zh}, **kwargs)

    def describe(self):
        return {"id": self.id, "catalog": self.catalog, "stage": self.stage, "severity": self.severity,
                "goal": self.goal, "title": self.title, "doc": self.doc}


REGISTRY: dict[str, Rule] = {}


def rule(id: str, *, catalog: str, stage: str, severity: str, goal: str, en: str, zh: str):
    """Decorator registering a check. The function receives (rule, *context) and yields Issues."""
    assert stage in STAGES and severity in SEVERITIES and goal in GOALS, (stage, severity, goal)

    def wrap(fn):
        if id in REGISTRY:
            raise ValueError(f"duplicate rule id {id}")
        REGISTRY[id] = Rule(id=id, catalog=catalog, stage=stage, severity=severity, goal=goal,
                            title={"en": en, "zh": zh}, check=fn, doc=(fn.__doc__ or "").strip())
        return fn

    return wrap


def run(stage: str, *context, prefix: str | None = None, only: Iterable[str] | None = None,
        disabled: Iterable[str] = ()) -> list[Issue]:
    """Run every registered rule for a stage. A crashing rule reports itself instead of
    taking the whole check down."""
    wanted = set(only) if only is not None else None
    off = set(disabled)
    issues: list[Issue] = []
    for r in REGISTRY.values():
        if r.stage != stage or r.id in off or (wanted is not None and r.id not in wanted):
            continue
        if prefix is not None and not r.id.startswith(prefix):
            continue
        try:
            issues.extend(r.check(r, *context) or ())
        except Exception as error:  # pragma: no cover - defensive
            issues.append(Issue(rule=r.id, catalog=r.catalog, severity="hint", goal="workflow",
                                message={"en": f"Check {r.id} failed internally: {error}",
                                         "zh": f"检查 {r.id} 内部出错：{error}"}))
    order = {s: i for i, s in enumerate(SEVERITIES)}
    issues.sort(key=lambda i: (order[i.severity], i.line if i.line is not None else 10**9))
    return issues


def catalog() -> list[dict]:
    return [r.describe() for r in sorted(REGISTRY.values(), key=lambda r: (r.catalog, r.id))]
