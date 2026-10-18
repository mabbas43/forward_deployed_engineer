"""P8 — per-ticket event streams (the worker publishes graph `updates`; the API serves them as SSE).
In-memory for dev; Redis Streams (XADD/XREAD) in production so any API replica can serve any ticket."""

import asyncio
import json
import threading
from collections import defaultdict


class EventBus:
    def __init__(self):
        self.history: dict[str, list[dict]] = defaultdict(list)
        self._lock = threading.Lock()

    def publish(self, stream: str, event: dict) -> None:
        with self._lock:
            self.history[stream].append(json.loads(json.dumps(event, default=str)))

    def read(self, stream: str, start: int = 0) -> list[dict]:
        return self.history.get(stream, [])[start:]

    async def follow(self, stream: str, timeout: float = 300, poll: float = 0.2):
        """Async generator for SSE: replay history, then tail until a terminal event or timeout."""
        i, waited = 0, 0.0
        while waited < timeout:
            evs = self.read(stream, i)
            for e in evs:
                yield e
                if e.get("type") in {"resolved", "awaiting_approval", "failed"}:
                    return
            i += len(evs)
            await asyncio.sleep(poll)
            waited += poll
