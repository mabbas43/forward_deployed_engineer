"""P7 — production run records + online scores + alerts (SQLite locally; Postgres in production).

Traces are raw material for datasets, not just a debugging aid: every served ticket becomes a `runs` row
that the online evaluator samples, judges and turns into `scores`.
"""

import json
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path

from atlas.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  trace_id TEXT PRIMARY KEY, ts REAL, tenant TEXT, route TEXT, category TEXT, escalated INTEGER, blocked INTEGER,
  latency_ms INTEGER, usd REAL, ticket_text TEXT, resolution TEXT, context_text TEXT, rating INTEGER,
  versions TEXT, variant TEXT
);
CREATE TABLE IF NOT EXISTS scores (trace_id TEXT, key TEXT, score REAL, ts REAL, source TEXT);
CREATE TABLE IF NOT EXISTS alerts (ts REAL, kind TEXT, key TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS runs_ts ON runs(ts);
CREATE INDEX IF NOT EXISTS scores_ts ON scores(ts, key);
"""


class Metrics:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def record_run(self, **r) -> None:
        cols = ["trace_id", "ts", "tenant", "route", "category", "escalated", "blocked", "latency_ms", "usd",
                "ticket_text", "resolution", "context_text", "rating", "versions", "variant"]
        r.setdefault("ts", time.time())
        r["versions"] = json.dumps(r.get("versions", {}))
        with self._lock:
            self.conn.execute(f"INSERT OR REPLACE INTO runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                              [r.get(c) for c in cols])

    def rate(self, trace_id: str, rating: int) -> None:
        self.conn.execute("UPDATE runs SET rating=? WHERE trace_id=?", (rating, trace_id))

    def add_score(self, trace_id: str, key: str, score: float, source: str = "online", ts: float | None = None):
        self.conn.execute("INSERT INTO scores VALUES (?,?,?,?,?)", (trace_id, key, score, ts or time.time(), source))

    def alert(self, kind: str, key: str, detail: dict) -> None:
        self.conn.execute("INSERT INTO alerts VALUES (?,?,?,?)", (time.time(), kind, key, json.dumps(detail)))

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.conn.execute(sql, params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


@lru_cache
def get_metrics() -> Metrics:
    return Metrics(settings.data_dir / "metrics.sqlite")
