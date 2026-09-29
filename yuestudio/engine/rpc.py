"""Client side of the worker protocol: one subprocess, JSON lines, futures per request."""
from __future__ import annotations

import collections
import json
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

from yuestudio_worker import protocol as P

log = logging.getLogger("yuestudio.worker")


class WorkerError(Exception):
    def __init__(self, code: str, message: str, trace: str = ""):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.trace = code, message, trace


class WorkerDied(WorkerError):
    def __init__(self, message: str, stderr_tail: str = ""):
        super().__init__("DIED", message, stderr_tail)


class WorkerProcess:
    def __init__(self, python: str, pythonpath: list[str], cwd: Path, env: dict | None = None):
        self.python = python
        self.pythonpath = pythonpath
        self.cwd = Path(cwd)
        self.extra_env = env or {}
        self.proc: subprocess.Popen | None = None
        self.pending: dict[str, Future] = {}
        self.handlers: dict[str, callable] = {}
        self.lock = threading.Lock()
        self.stderr_tail: collections.deque[str] = collections.deque(maxlen=400)
        self.last_heartbeat = 0.0
        self.heartbeat: dict = {}
        self.ready = threading.Event()
        self.on_global_event = None

    # ------------------------------------------------------------------ lifecycle
    def start(self, timeout: float = 60.0) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
        env.update({"PYTHONPATH": os.pathsep.join(self.pythonpath), "PYTHONUNBUFFERED": "1",
                    "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1",
                    "MLX_ENABLE_TF32": "0", "TOKENIZERS_PARALLELISM": "false"})
        env.update(self.extra_env)
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.ready.clear()
        self.proc = subprocess.Popen([self.python, "-m", "yuestudio_worker"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(self.cwd), env=env,
                                     start_new_session=True)
        threading.Thread(target=self._read_stdout, name="worker-stdout", daemon=True).start()
        threading.Thread(target=self._read_stderr, name="worker-stderr", daemon=True).start()
        if not self.ready.wait(timeout):
            tail = self.tail()
            self.kill()
            raise WorkerDied(f"worker did not start within {timeout:.0f}s", tail)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def tail(self, n: int = 60) -> str:
        return "\n".join(list(self.stderr_tail)[-n:])

    def terminate(self, grace: float = 5.0) -> None:
        if not self.alive():
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(grace)
        except subprocess.TimeoutExpired:
            self.kill()

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                self.proc.kill()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                pass

    def stop(self) -> None:
        if self.alive():
            try:
                self.call("shutdown", {}, timeout=10)
            except Exception:
                pass
        self.terminate()

    # ------------------------------------------------------------------ io threads
    def _read_stdout(self):
        proc = self.proc
        for raw in proc.stdout:
            try:
                msg = json.loads(raw.decode("utf-8"))
            except ValueError:
                self.stderr_tail.append("[stdout-noise] " + raw.decode("utf-8", "replace").rstrip())
                continue
            if "ev" in msg:
                self._event(msg)
                continue
            fut = self.pending.pop(msg.get("id"), None)
            self.handlers.pop(msg.get("id"), None)
            if fut is None:
                continue
            if msg.get("ok"):
                fut.set_result(msg.get("r"))
            else:
                err = msg.get("err") or {}
                fut.set_exception(WorkerError(err.get("code", "INTERNAL"), err.get("msg", ""), err.get("trace", "")))
        code = proc.wait()
        tail = self.tail()
        for rid, fut in list(self.pending.items()):
            if not fut.done():
                fut.set_exception(WorkerDied(f"worker exited with code {code}", tail))
            self.pending.pop(rid, None)
        self.handlers.clear()

    def _read_stderr(self):
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self.stderr_tail.append(line)
                log.debug(line)

    def _event(self, msg: dict):
        kind = msg.get("ev")
        if kind == P.EV_READY:
            self.ready.set()
        elif kind == P.EV_HEARTBEAT:
            self.last_heartbeat = time.time()
            self.heartbeat = msg
        handler = self.handlers.get(msg.get("id"))
        if handler is not None:
            try:
                handler(msg)
            except Exception:  # pragma: no cover
                log.exception("event handler failed")
        if self.on_global_event is not None:
            self.on_global_event(msg)

    # ------------------------------------------------------------------ calls
    def send(self, method: str, params: dict, on_event=None) -> tuple[str, Future]:
        if not self.alive():
            raise WorkerDied("worker is not running", self.tail())
        rid = uuid.uuid4().hex[:12]
        fut: Future = Future()
        self.pending[rid] = fut
        if on_event is not None:
            self.handlers[rid] = on_event
        line = json.dumps({"v": P.PROTOCOL_VERSION, "id": rid, "m": method, "p": params}, ensure_ascii=False) + "\n"
        with self.lock:
            try:
                self.proc.stdin.write(line.encode("utf-8"))
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                self.pending.pop(rid, None)
                raise WorkerDied(f"write failed: {error}", self.tail()) from error
        return rid, fut

    def call(self, method: str, params: dict, on_event=None, timeout: float | None = None):
        rid, fut = self.send(method, params, on_event)
        try:
            return fut.result(timeout)
        except FutureTimeout as error:
            raise WorkerError("TIMEOUT", f"{method} exceeded {timeout:.0f}s") from error

    def control(self, method: str, params: dict | None = None, timeout: float = 5.0):
        return self.call(method, params or {}, timeout=timeout)
