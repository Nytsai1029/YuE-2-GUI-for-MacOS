"""Quality presets. They are budgets, not fixed counts: the Director stops early as soon
as a plan/take passes every gate with a comfortable score."""
from __future__ import annotations

PRESETS = {
    "draft": {"plans": 1, "min_plans": 1, "takes": 1, "min_takes": 1, "audition_steps": 8, "final_steps": None,
              "plan_accept": 0, "take_accept": 0, "max_plan_attempts": 1, "asr_passes": 1},
    "standard": {"plans": 3, "min_plans": 2, "takes": 2, "min_takes": 1, "audition_steps": 8, "final_steps": 32,
                 "plan_accept": 78, "take_accept": 75, "max_plan_attempts": 2, "asr_passes": 1},
    "best": {"plans": 6, "min_plans": 3, "takes": 4, "min_takes": 2, "audition_steps": 8, "final_steps": 32,
             "plan_accept": 85, "take_accept": 82, "max_plan_attempts": 3, "asr_passes": 2},
}


def resolve(preset: str, overrides: dict | None = None) -> dict:
    cfg = dict(PRESETS.get(preset, PRESETS["standard"]))
    for k, v in (overrides or {}).items():
        if v is not None and k in cfg:
            cfg[k] = v
    cfg["preset"] = preset if preset in PRESETS else "standard"
    return cfg
