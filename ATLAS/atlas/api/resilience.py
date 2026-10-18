"""P8 — resilience primitives. Design it like a payments system: idempotent, rate-limited, failure-isolated.

- CircuitBreaker: open after N consecutive failures; after `reset_after` s allow one half-open probe;
  success closes it, failure re-opens. Callers fall back (other model / "queued for human") while open.
- TokenBucket: per-tenant (and per-model) rate limits with refill. Redis version: an atomic Lua script.
- Dedupe: client Idempotency-Key → first claim wins for `ttl` seconds; replays get the original ticket id.
"""

import threading
import time


class CircuitOpen(Exception):
    def __init__(self, name: str):
        super().__init__(f"circuit '{name}' is open")
        self.name = name


class CircuitBreaker:
    def __init__(self, name: str, fail_threshold: int = 5, reset_after: float = 60.0, clock=time.monotonic):
        self.name, self.fail_threshold, self.reset_after, self.clock = name, fail_threshold, reset_after, clock
        self.failures, self.opened_at, self._lock = 0, None, threading.Lock()

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.reset_after else "open"

    def before(self):
        if self.state == "open":
            raise CircuitOpen(self.name)

    def on_success(self):
        with self._lock:
            self.failures, self.opened_at = 0, None

    def on_failure(self):
        with self._lock:
            self.failures += 1
            if self.failures >= self.fail_threshold or self.state == "half_open":
                self.opened_at = self.clock()

    def call(self, fn, *a, **kw):
        self.before()
        try:
            r = fn(*a, **kw)
        except Exception:
            self.on_failure()
            raise
        self.on_success()
        return r

    async def acall(self, fn, *a, **kw):
        self.before()
        try:
            r = await fn(*a, **kw)
        except Exception:
            self.on_failure()
            raise
        self.on_success()
        return r


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: int, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate_per_s, burst, clock
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str, n: int = 1) -> bool:
        with self._lock:
            tokens, last = self._state.get(key, (float(self.burst), self.clock()))
            now = self.clock()
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            ok = tokens >= n
            self._state[key] = (tokens - n if ok else tokens, now)
            return ok


class Dedupe:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._d: dict[str, tuple[float, str | None]] = {}
        self._lock = threading.Lock()

    def claim(self, key: str, ttl: float = 86400) -> bool:
        """SET NX EX semantics: True for the first caller within ttl."""
        with self._lock:
            now = self.clock()
            hit = self._d.get(key)
            if hit and hit[0] > now:
                return False
            self._d[key] = (now + ttl, None)
            return True

    def remember(self, key: str, value: str) -> None:
        with self._lock:
            exp, _ = self._d.get(key, (self.clock() + 86400, None))
            self._d[key] = (exp, value)

    def get(self, key: str) -> str | None:
        hit = self._d.get(key)
        return hit[1] if hit and hit[0] > self.clock() else None


TOKEN_BUCKET_LUA = """
-- KEYS[1]=bucket key; ARGV: rate, burst, now, n  → 1 if taken else 0   (atomic in Redis)
local s = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(s[1]) or tonumber(ARGV[2]); local ts = tonumber(s[2]) or tonumber(ARGV[3])
tokens = math.min(tonumber(ARGV[2]), tokens + (tonumber(ARGV[3]) - ts) * tonumber(ARGV[1]))
local ok = tokens >= tonumber(ARGV[4]); if ok then tokens = tokens - tonumber(ARGV[4]) end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', ARGV[3]); redis.call('EXPIRE', KEYS[1], 3600)
return ok and 1 or 0
"""
