"""Find the user's existing mlx-Yue install and model folders. Never installs anything."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HF_MODEL = "models--vanch007--mlx-Yue2-3B"
HF_VAE = "models--m-a-p--YuE2-Vae"
COMMON = ["~/mlx-Yue", "~/Projects/mlx-Yue", "~/Developer/mlx-Yue", "~/Desktop/mlx-Yue", "~/code/mlx-Yue",
          "~/src/mlx-Yue", "~/git/mlx-Yue", "~/Documents/mlx-Yue", "~/Downloads/mlx-Yue"]


def hf_cache() -> Path:
    return Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME", "~/.cache/huggingface")) / "hub").expanduser()


def snapshots(repo_dir: str) -> list[Path]:
    root = hf_cache() / repo_dir / "snapshots"
    return sorted(root.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []


def looks_like_model(path: Path) -> dict:
    files = {p.name for p in path.glob("*")} if path.is_dir() else set()
    precisions = [p for p in ("bf16", "8bit", "4bit") if f"ar-{p}.safetensors" in files]
    return {"path": str(path), "precisions": precisions, "converted": "conversion.json" in files,
            "tokenizer": "qwen.tiktoken" in files, "nar": any(f.startswith("nar-") for f in files)}


def looks_like_vae(path: Path) -> bool:
    return path.is_dir() and (path / "model.safetensors").exists() and (path / "config.json").exists()


def probe_python(python: str) -> dict:
    code = ("import json,sys\nout={'python':sys.version.split()[0]}\n"
            "try:\n import lyra;out['lyra']=True\nexcept Exception as e:\n out['lyra']=False;out['error']=repr(e)\n"
            "try:\n from importlib.metadata import version;out['mlx_yue']=version('mlx-yue');out['mlx']=version('mlx')\n"
            "except Exception:\n pass\nprint(json.dumps(out))")
    try:
        res = subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=60,
                             env={**{k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
                                  "PYTHONNOUSERSITE": "1"})
        return json.loads(res.stdout.strip().splitlines()[-1]) if res.stdout.strip() else \
            {"lyra": False, "error": res.stderr[-400:]}
    except Exception as error:
        return {"lyra": False, "error": repr(error)}


def detect(mlx_yue_dir: str | None = None) -> dict:
    candidates = [mlx_yue_dir] if mlx_yue_dir else [str(Path(c).expanduser()) for c in COMMON]
    found = {"mlx_yue_dir": None, "python": None, "python_info": None, "models": [], "vaes": [], "notes": []}
    for c in candidates:
        if not c:
            continue
        root = Path(c).expanduser()
        py = root / ".venv" / "bin" / "python"
        if py.exists():
            info = probe_python(str(py))
            found.update(mlx_yue_dir=str(root), python=str(py), python_info=info)
            for sub in ("models/converted", "models", "converted"):
                if (root / sub).is_dir():
                    m = looks_like_model(root / sub)
                    if m["precisions"]:
                        found["models"].append(m)
            for sub in ("models/vae", "vae", "models/YuE2-Vae"):
                if looks_like_vae(root / sub):
                    found["vaes"].append(str(root / sub))
            break
    for snap in snapshots(HF_MODEL):
        m = looks_like_model(snap)
        if m["precisions"]:
            found["models"].append(m)
    for snap in snapshots(HF_VAE):
        if looks_like_vae(snap):
            found["vaes"].append(str(snap))
    if found["python"] and not (found["python_info"] or {}).get("lyra"):
        found["notes"].append("Found a .venv but `import lyra` failed there. Run mlx-Yue's own setup first.")
    if not found["models"]:
        found["notes"].append("No converted model found. Point Model folder at your mlx-Yue2-3B weights.")
    return found
