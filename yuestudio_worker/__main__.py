"""Engine worker entry point: ``<mlx-Yue venv python> -m yuestudio_worker``.

* fd hygiene: the real stdout becomes a private RPC channel; fd 1 is pointed at stderr so
  tqdm/MLX/print output can never corrupt the protocol.
* The main thread owns the GPU and serves one request at a time.
* A reader thread answers ping/cancel immediately, even while a job runs.
* A heartbeat thread reports memory so the supervisor can see the process is alive.
"""
from __future__ import annotations

import json
import os
import platform
import queue
import sys
import threading
import time
import traceback

from . import protocol as P


class Channel:
    def __init__(self):
        rpc_fd = os.dup(1)
        os.dup2(2, 1)  # anything printed to "stdout" now lands in stderr (logged by the server)
        sys.stdout = sys.stderr
        self._out = os.fdopen(rpc_fd, "w", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def send(self, message):
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
        with self._lock:
            self._out.write(line + "\n")
            self._out.flush()


def _rss():
    try:
        import psutil

        return psutil.Process().memory_info().rss
    except Exception:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


class Worker:
    def __init__(self):
        self.ch = Channel()
        self.inbox = queue.Queue()
        self.cancel_flags = {}
        self.current = None
        self.running = True
        from .lyra_adapter import LyraAdapter

        self.adapter = LyraAdapter()

    # ------------------------------------------------------------------ threads
    def reader(self):
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                self.ch.send({"ev": P.EV_LOG, "id": None, "level": "error", "msg": "unparseable request"})
                continue
            method = msg.get("m")
            if method == "ping":
                self.ch.send({"id": msg.get("id"), "ok": True, "r": {"pong": time.time(), "busy": self.current}})
            elif method == "cancel":
                target = (msg.get("p") or {}).get("target")
                flag = self.cancel_flags.get(target)
                if flag is not None:
                    flag.set()
                self.ch.send({"id": msg.get("id"), "ok": True, "r": {"cancelled": target, "found": flag is not None}})
            else:
                self.inbox.put(msg)
        self.running = False
        self.inbox.put(None)  # stdin closed: server went away

    def heartbeat(self):
        while self.running:
            self.ch.send({"ev": P.EV_HEARTBEAT, "id": None, "rss": _rss(), "busy": self.current, "t": time.time()})
            time.sleep(2.0)

    # ------------------------------------------------------------------ main loop
    def serve(self):
        threading.Thread(target=self.reader, name="rpc-reader", daemon=True).start()
        threading.Thread(target=self.heartbeat, name="heartbeat", daemon=True).start()
        self.ch.send({"ev": P.EV_READY, "id": None, "protocol": P.PROTOCOL_VERSION, "pid": os.getpid()})
        while self.running:
            msg = self.inbox.get()
            if msg is None:
                break
            self.handle(msg)

    def handle(self, msg):
        rid, method, params = msg.get("id"), msg.get("m"), msg.get("p") or {}
        if msg.get("v") != P.PROTOCOL_VERSION:
            return self.fail(rid, P.E_BAD_REQUEST, f"protocol {msg.get('v')} != {P.PROTOCOL_VERSION}")
        handler = getattr(self, "m_" + str(method), None)
        if handler is None:
            return self.fail(rid, P.E_BAD_REQUEST, f"unknown method {method!r}")
        flag = threading.Event()
        self.cancel_flags[rid] = flag
        self.current = rid
        try:
            result = handler(rid, params, flag)
            self.ch.send({"id": rid, "ok": True, "r": result})
        except BaseException as error:  # noqa: BLE001 - everything must be reported
            code, text = classify(error)
            self.fail(rid, code, text, traceback.format_exc())
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
        finally:
            self.current = None
            self.cancel_flags.pop(rid, None)

    def fail(self, rid, code, text, trace=""):
        self.ch.send({"id": rid, "ok": False, "err": {"code": code, "msg": text, "trace": trace[-6000:]}})

    # ------------------------------------------------------------------ helpers
    def _cancelled(self, flag):
        return flag.is_set

    def _token_stream(self, rid, flag, phase, chunk_every=250):
        """on_token callback: throttled progress + streamed semantic token chunks."""
        state = {"n": 0, "buf": [], "start": 0, "last": 0.0}

        def on_token(token_phase, token):
            if flag.is_set():
                raise InterruptedError("cancelled")
            state["n"] += 1
            if phase == "semantic":
                state["buf"].append(int(token))
                if len(state["buf"]) >= chunk_every:
                    self.ch.send({"ev": P.EV_TOKENS, "id": rid, "phase": phase,
                                  "start": state["start"], "chunk": state["buf"]})
                    state["start"] += len(state["buf"])
                    state["buf"] = []
            now = time.monotonic()
            if now - state["last"] > 0.2:
                state["last"] = now
                self.ch.send({"ev": P.EV_PROGRESS, "id": rid, "phase": phase, "done": state["n"], "total": None})

        def flush():
            if state["buf"]:
                self.ch.send({"ev": P.EV_TOKENS, "id": rid, "phase": phase, "start": state["start"],
                              "chunk": state["buf"]})
                state["buf"] = []

        return on_token, flush

    # ------------------------------------------------------------------ methods
    def m_hello(self, rid, p, flag):
        return {"protocol": P.PROTOCOL_VERSION, "python": platform.python_version(),
                "platform": platform.platform(), "machine": platform.machine(), "pid": os.getpid()}

    def m_introspect(self, rid, p, flag):
        return self.adapter.introspect()

    def m_load(self, rid, p, flag):
        self.ch.send({"ev": P.EV_PROGRESS, "id": rid, "phase": "load", "done": 0, "total": 1})
        return self.adapter.load(p["model"], p["vae"], converted_dir=p.get("converted_dir"),
                                 precision=p.get("precision", "8bit"),
                                 memory_budget_gib=p.get("memory_budget_gib"),
                                 ode_steps=p.get("ode_steps", 32), require_ac=p.get("require_ac", False))

    def m_unload(self, rid, p, flag):
        self.adapter.unload()
        return {"unloaded": True}

    def m_plan(self, rid, p, flag):
        on_token, _ = self._token_stream(rid, flag, "abc")
        return self.adapter.plan(p["out_dir"], p["style"], p["lyrics"], cot=p.get("cot", "full"),
                                 seed=p.get("seed", 0), abc=p.get("abc"), abc_sampling=p.get("abc_sampling"),
                                 cfg_scale=p.get("cfg_scale"), cancelled=flag.is_set, on_token=on_token)

    def m_semantic(self, rid, p, flag):
        on_token, flush = self._token_stream(rid, flag, "semantic", int(p.get("chunk_every", 250)))
        try:
            return self.adapter.semantic(p["out_dir"], p["plan_dir"], p["seed"], sampling=p.get("sampling"),
                                         cancelled=flag.is_set, on_token=on_token)
        finally:
            flush()

    def m_render(self, rid, p, flag):
        state = {"last": 0.0}

        def on_progress(phase, done, total):
            if flag.is_set():
                raise InterruptedError("cancelled")
            now = time.monotonic()
            if now - state["last"] > 0.2 or done == total:
                state["last"] = now
                self.ch.send({"ev": P.EV_PROGRESS, "id": rid, "phase": phase, "done": done, "total": total})

        return self.adapter.render(p["out_dir"], p["plan_dir"], p["tokens_path"], p["seed"],
                                   ode_steps=p.get("ode_steps", 32), noise_seed=p.get("noise_seed"),
                                   cancelled=flag.is_set, on_progress=on_progress,
                                   keep_latents=p.get("keep_latents", False))

    def m_abc_check(self, rid, p, flag):
        return self.adapter.abc_check(p["abc"], compare_to=p.get("compare_to"),
                                      allow_tempo_change=p.get("allow_tempo_change", False))

    def m_shutdown(self, rid, p, flag):
        self.adapter.unload()
        self.running = False
        return {"bye": True}


def classify(error):
    from .lyra_adapter import NotLoaded

    text = f"{type(error).__name__}: {error}"
    lowered = text.lower()
    if isinstance(error, InterruptedError) or "cancel" in lowered:
        return P.E_CANCELLED, text
    if isinstance(error, NotLoaded):
        return P.E_NOT_LOADED, text
    if isinstance(error, MemoryError) or "memory" in lowered or "oom" in lowered:
        return P.E_OOM, text
    if "context" in lowered and "exceed" in lowered:
        return P.E_CONTEXT, text
    if isinstance(error, (KeyError, TypeError, ValueError)):
        return P.E_BAD_REQUEST, text
    return P.E_INTERNAL, text


def main():
    os.environ.setdefault("MLX_ENABLE_TF32", "0")
    Worker().serve()


if __name__ == "__main__":
    main()
