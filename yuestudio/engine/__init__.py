"""Engine supervisor: owns the worker process, keeps the model resident, restarts after
crashes, and escalates cancellation (flag -> SIGTERM -> SIGKILL -> lazy reload).

The same class drives the real mlx-Yue worker and the fake engine; only the Python
interpreter and PYTHONPATH differ.
"""
from __future__ import annotations

import logging
import shutil
import sys
import threading
import time
from pathlib import Path

import yuestudio_worker

from ..config import FAKE_LYRA
from .rpc import WorkerDied, WorkerError, WorkerProcess

log = logging.getLogger("yuestudio.engine")


class EngineUnavailable(Exception):
    pass


class Engine:
    def __init__(self, data_dir: Path, settings_fn):
        self.data_dir = Path(data_dir)
        self.settings_fn = settings_fn
        self.worker: WorkerProcess | None = None
        self.loaded_profile: dict | None = None
        self.caps: dict = {}
        self.hello: dict = {}
        self.status = "stopped"          # stopped | starting | idle | loading | busy | error
        self.status_detail = ""
        self.lock = threading.RLock()
        self.current_rid: str | None = None
        self.listeners = []
        self.restarts = 0

    # ------------------------------------------------------------------ helpers
    def _emit(self, **event):
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception:  # pragma: no cover
                log.exception("engine listener failed")

    def _set_status(self, status, detail=""):
        self.status, self.status_detail = status, detail
        self._emit(kind="engine", status=status, detail=detail)

    def config(self) -> dict:
        return self.settings_fn()["engine"]

    def _stage_worker_code(self) -> Path:
        """Copy the worker package to a private runtime folder so PYTHONPATH exposes nothing else."""
        src = Path(yuestudio_worker.__file__).parent
        dst_root = self.data_dir / "runtime" / "worker"
        dst = dst_root / "yuestudio_worker"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst_root

    def interpreter(self) -> tuple[str, list[str]]:
        cfg = self.config()
        code_root = str(self._stage_worker_code())
        if cfg.get("mode") == "fake":
            return sys.executable, [code_root, str(FAKE_LYRA)]
        python = cfg.get("python") or ""
        if not python and cfg.get("mlx_yue_dir"):
            candidate = Path(cfg["mlx_yue_dir"]).expanduser() / ".venv" / "bin" / "python"
            python = str(candidate) if candidate.exists() else ""
        if not python:
            raise EngineUnavailable("Choose your mlx-Yue folder in Settings (the one with its .venv).")
        return python, [code_root]

    def profile(self) -> dict:
        cfg = self.config()
        return {k: cfg.get(k) for k in ("mode", "model_dir", "vae_dir", "converted_dir", "precision",
                                        "memory_budget_gib", "require_ac")}

    # ------------------------------------------------------------------ lifecycle
    def ensure_started(self) -> None:
        with self.lock:
            if self.worker is not None and self.worker.alive():
                return
            self._set_status("starting")
            python, path = self.interpreter()
            self.worker = WorkerProcess(python, path, self.data_dir / "runtime" / "cwd")
            self.worker.on_global_event = self._on_worker_event
            try:
                self.worker.start()
                self.hello = self.worker.call("hello", {}, timeout=30)
                self.caps = self.worker.call("introspect", {}, timeout=120)
            except WorkerError as error:
                self._set_status("error", str(error))
                raise
            self.loaded_profile = None
            self._set_status("idle")

    def ensure_loaded(self) -> None:
        self.ensure_started()
        with self.lock:
            profile = self.profile()
            if self.loaded_profile == profile:
                return
            cfg = self.config()
            if cfg.get("mode") != "fake" and (not cfg.get("model_dir") or not cfg.get("vae_dir")):
                raise EngineUnavailable("Choose the model and VAE folders in Settings.")
            self._set_status("loading", cfg.get("precision", "8bit"))
            params = {"model": cfg.get("model_dir") or str(self.data_dir), "vae": cfg.get("vae_dir") or str(self.data_dir),
                      "converted_dir": cfg.get("converted_dir") or None, "precision": cfg.get("precision", "8bit"),
                      "memory_budget_gib": cfg.get("memory_budget_gib"), "require_ac": cfg.get("require_ac", False)}
            try:
                result = self.worker.call("load", params, timeout=1800)
            except WorkerError as error:
                self._set_status("error", error.message)
                raise
            self.loaded_profile = profile
            self._set_status("idle", f"loaded in {result.get('load_seconds', 0):.1f}s")

    def restart(self) -> None:
        with self.lock:
            if self.worker is not None:
                self.worker.terminate()
            self.worker = None
            self.loaded_profile = None
            self.restarts += 1
            self._set_status("stopped", "restarting")

    def shutdown(self) -> None:
        with self.lock:
            if self.worker is not None:
                self.worker.stop()
            self.worker = None
            self.loaded_profile = None
            self._set_status("stopped")

    def _on_worker_event(self, msg):
        if msg.get("ev") == "heartbeat":
            self._emit(kind="heartbeat", rss=msg.get("rss"), busy=msg.get("busy"))

    # ------------------------------------------------------------------ calls
    def call(self, method: str, params: dict, on_event=None, timeout: float | None = None, retries: int = 1):
        """Run a GPU call. A crashed worker is restarted and the call retried once."""
        attempt = 0
        while True:
            self.ensure_loaded() if method not in ("abc_check",) else self.ensure_started()
            self._set_status("busy", method)
            try:
                rid, fut = self.worker.send(method, params, on_event)
                self.current_rid = rid
                try:
                    return fut.result(timeout)
                except TimeoutError as error:
                    raise WorkerError("TIMEOUT", f"{method} exceeded {timeout:.0f}s") from error
            except WorkerDied as error:
                log.warning("worker died during %s: %s", method, error.message)
                self.restart()
                attempt += 1
                if attempt > retries:
                    self._set_status("error", f"worker crashed during {method}")
                    raise
                self._emit(kind="engine", status="recovering", detail=f"worker crashed during {method}; retrying")
            finally:
                self.current_rid = None
                if self.worker is not None and self.worker.alive() and self.status == "busy":
                    self._set_status("idle")

    def cancel(self, grace: float = 8.0) -> bool:
        """Ask the running call to stop; kill the process if it doesn't within ``grace``."""
        worker, rid = self.worker, self.current_rid
        if worker is None or rid is None:
            return False
        try:
            worker.control("cancel", {"target": rid})
        except WorkerError:
            pass
        deadline = time.time() + grace
        while time.time() < deadline:
            if self.current_rid != rid:
                return True
            time.sleep(0.1)
        log.warning("cancel did not take effect in %.0fs; killing worker", grace)
        worker.terminate(grace=3.0)
        return True

    def info(self) -> dict:
        w = self.worker
        return {"status": self.status, "detail": self.status_detail, "loaded": self.loaded_profile is not None,
                "profile": self.loaded_profile, "caps": self.caps, "hello": self.hello, "restarts": self.restarts,
                "heartbeat": (w.heartbeat if w else {}), "alive": bool(w and w.alive()),
                "stderr_tail": (w.tail(40) if w else "")}
