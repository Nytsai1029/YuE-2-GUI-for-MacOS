"""Paths and settings. Settings live in SQLite (see db.py); this module owns defaults."""
from __future__ import annotations

import os
import platform
from pathlib import Path


def default_data_dir() -> Path:
    env = os.environ.get("YUESTUDIO_DATA")
    if env:
        return Path(env).expanduser()
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "YuE Studio"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "YuE Studio"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "yue-studio"


REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_LYRA = REPO_ROOT / "fake_lyra"

DEFAULT_SETTINGS = {
    "engine": {
        "mode": "real",                  # real | fake
        "mlx_yue_dir": "",               # checkout of vanch007/mlx-Yue (its .venv is used)
        "python": "",                    # explicit interpreter (overrides mlx_yue_dir/.venv)
        "model_dir": "",                 # converted weights (vanch007/mlx-Yue2-3B)
        "vae_dir": "",                   # m-a-p/YuE2-Vae
        "converted_dir": "",
        "precision": "8bit",             # bf16 | 8bit | 4bit
        "memory_budget_gib": None,
        "require_ac": False,
        "idle_unload_minutes": 0,        # 0 = keep resident
    },
    "asr": {"enabled": True, "provider": "auto", "model": "mlx-community/whisper-large-v3-turbo", "passes": 1},
    "quality": {"preset": "standard", "audition_steps": 8, "final_steps": 32},
    "mastering": {"enabled": True, "lufs": -14.0, "true_peak": -1.0},
    "retention": {"keep_losing_audio": False},
    "ui": {"language": "auto", "theme": "dark"},
    "server": {"lan": False, "token": ""},
    "calibration": {"abc_tokens_per_bar": 44.0, "ar_tok_s": None, "nar_s_per_audio_s_8": None,
                    "nar_s_per_audio_s_32": None},
}


def deep_merge(base: dict, update: dict) -> dict:
    out = dict(base)
    for k, v in (update or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
