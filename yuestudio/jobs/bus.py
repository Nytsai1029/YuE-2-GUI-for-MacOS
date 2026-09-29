"""In-process event bus with sequence numbers (SSE clients resume with Last-Event-ID)."""
from __future__ import annotations

import asyncio
import collections
import json
import threading
import time


class Bus:
    def __init__(self, keep: int = 2000):
        self.seq = 0
        self.events: collections.deque = collections.deque(maxlen=keep)
        self.lock = threading.Lock()
        self.waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()

    def publish(self, topic: str, **payload) -> int:
        with self.lock:
            self.seq += 1
            event = {"seq": self.seq, "topic": topic, "t": time.time(), **payload}
            self.events.append(event)
            waiters = list(self.waiters)
        for loop, ev in waiters:
            try:
                loop.call_soon_threadsafe(ev.set)
            except RuntimeError:
                pass
        return self.seq

    def since(self, seq: int) -> list[dict]:
        with self.lock:
            return [e for e in self.events if e["seq"] > seq]

    async def stream(self, last: int = 0, ping: float = 15.0):
        loop = asyncio.get_running_loop()
        waiter = (loop, asyncio.Event())
        with self.lock:
            self.waiters.add(waiter)
        try:
            while True:
                for event in self.since(last):
                    last = event["seq"]
                    yield f"id: {last}\nevent: {event['topic']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                waiter[1].clear()
                try:
                    await asyncio.wait_for(waiter[1].wait(), ping)
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            with self.lock:
                self.waiters.discard(waiter)
