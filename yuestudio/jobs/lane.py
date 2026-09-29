"""The single GPU lane: persistent FIFO of jobs, one at a time (the model is not
thread-safe and unified memory is shared). Jobs survive restarts: anything that was
running when the server stopped is marked 'interrupted' and can be resumed, which
continues from the last finished stage."""
from __future__ import annotations

import logging
import threading
import time

from ..director.pipeline import Cancelled, Director

log = logging.getLogger("yuestudio.lane")


class Lane:
    def __init__(self, db, director: Director, engine, bus):
        self.db, self.director, self.engine, self.bus = db, director, engine, bus
        self.wake = threading.Event()
        self.current: dict | None = None
        self.cancel_event = threading.Event()
        self.stopped = False
        self.thread = threading.Thread(target=self._loop, name="gpu-lane", daemon=True)

    def start(self):
        self.recover()
        self.thread.start()

    def stop(self):
        self.stopped = True
        self.cancel_event.set()
        self.wake.set()

    # ------------------------------------------------------------------ public
    def submit(self, kind: str, take_id: str | None, params: dict | None = None) -> dict:
        job = self.db.insert("jobs", {"take_id": take_id, "kind": kind, "state": "queued", "params": params or {}})
        if take_id and kind != "warmup":
            self.db.update("takes", take_id, status="queued")
        self.bus.publish("job", job_id=job["id"], take_id=take_id, state="queued", kind=kind)
        self.wake.set()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.db.get("jobs", job_id)
        if job is None:
            return False
        if job["state"] == "queued":
            self.db.update("jobs", job_id, state="cancelled", finished=time.time())
            if job["take_id"] and job["kind"] != "warmup":
                self.db.update("takes", job["take_id"], status="cancelled")
            self.bus.publish("job", job_id=job_id, take_id=job["take_id"], state="cancelled")
            return True
        if self.current and self.current["id"] == job_id:
            self.cancel_event.set()
            threading.Thread(target=self.engine.cancel, daemon=True).start()
            return True
        return False

    def queue(self) -> list[dict]:
        return self.db.all("SELECT * FROM jobs WHERE state IN ('queued','running') ORDER BY created")

    def recover(self):
        for job in self.db.all("SELECT * FROM jobs WHERE state='running'"):
            self.db.update("jobs", job["id"], state="interrupted", finished=time.time())
            if job["take_id"] and job["kind"] != "warmup":
                self.db.update("takes", job["take_id"], status="interrupted")
        for take in self.db.all("SELECT id FROM takes WHERE status IN ('running','queued')"):
            queued = self.db.one("SELECT id FROM jobs WHERE take_id=? AND state='queued'", (take["id"],))
            if not queued:
                self.db.update("takes", take["id"], status="interrupted")

    # ------------------------------------------------------------------ loop
    def _next(self) -> dict | None:
        return self.db.one("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1")

    def _loop(self):
        while not self.stopped:
            job = self._next()
            if job is None:
                self.wake.wait(2.0)
                self.wake.clear()
                continue
            self.current = job
            self.cancel_event = threading.Event()
            self.db.update("jobs", job["id"], state="running", started=time.time())
            self.bus.publish("job", job_id=job["id"], take_id=job["take_id"], state="running", kind=job["kind"])
            state, error = "done", None
            try:
                self._run(job)
                take = self.db.get("takes", job["take_id"]) if job["take_id"] else None
                if take and take["status"] == "cancelled":
                    state = "cancelled"
            except Cancelled:
                state = "cancelled"
            except Exception as exc:  # recorded on the take by the Director too
                state, error = "failed", {"type": type(exc).__name__, "message": str(exc)}
                log.exception("job %s failed", job["id"])
            self.db.update("jobs", job["id"], state=state, error=error, finished=time.time())
            self.bus.publish("job", job_id=job["id"], take_id=job["take_id"], state=state, error=error)
            self.current = None

    def _run(self, job: dict):
        p = job.get("params") or {}
        if job["kind"] == "take":
            self.director.run_take(job["take_id"], self.cancel_event)
        elif job["kind"] == "render_plan":
            self.director.run_render_plan(job["take_id"], p["plan_id"], int(p.get("n", 2)), self.cancel_event)
        elif job["kind"] == "finalize":
            self.director.run_finalize(job["take_id"], p["candidate_id"], self.cancel_event,
                                       noise_seed=p.get("noise_seed"), steps=p.get("steps"))
        elif job["kind"] == "warmup":
            self.engine.ensure_loaded()
        else:
            raise ValueError(f"unknown job kind {job['kind']}")
