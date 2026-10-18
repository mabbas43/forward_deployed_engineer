"""P6 — the append-only audit trail, plus GDPR access (export) and erasure (forget).

Every LLM call, tool call, guardrail verdict, approval, route decision and promotion is an event with:
trace_id, tenant, user_hash, role, model, prompt_version, route, tool, payload, timestamp.
Append-only is enforced by the database (triggers abort UPDATE/DELETE) — the only exception is the
erasure procedure, which flips a guarded flag, hashes identities, and logs itself.
Production: Postgres with INSERT-only grants for the app role, or a stream into immutable storage.
"""

import hashlib
import json
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path

from atlas.config import settings
from atlas.logging import get_logger

log = get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, event TEXT NOT NULL, trace_id TEXT, tenant TEXT, user_hash TEXT, role TEXT,
  model TEXT, prompt_version TEXT, route TEXT, tool TEXT, ticket_text TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS threads (thread_id TEXT PRIMARY KEY, tenant TEXT, user_hash TEXT, created REAL);
CREATE TABLE IF NOT EXISTS erasure_mode (enabled INTEGER NOT NULL);
INSERT INTO erasure_mode SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM erasure_mode);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
  WHEN (SELECT enabled FROM erasure_mode) = 0 BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
  BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE INDEX IF NOT EXISTS audit_user ON audit(user_hash);
CREATE INDEX IF NOT EXISTS audit_event ON audit(event, ts);
"""

COLUMNS = {"trace_id", "tenant", "user_hash", "role", "model", "prompt_version", "route", "tool", "ticket_text"}


def user_hash(user_id: str) -> str:
    """Pseudonymize identities in logs. (Salt per deployment; rotate per policy.)"""
    return hashlib.sha256(f"{settings.jwt_secret}:{user_id.lower()}".encode()).hexdigest()[:16]


class AuditLog:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def write(self, event: str, **fields) -> None:
        cols = {k: (str(v) if v is not None else None) for k, v in fields.items() if k in COLUMNS}
        payload = {k: v for k, v in fields.items() if k not in COLUMNS}
        names = ["ts", "event", *cols, "payload"]
        vals = [time.time(), event, *cols.values(), json.dumps(payload, default=str)]
        with self._lock:
            self.conn.execute(f"INSERT INTO audit ({', '.join(names)}) VALUES ({', '.join('?' * len(vals))})", vals)
        log.info("audit", audit_event=event, **{k: v for k, v in cols.items() if k != "ticket_text"})

    def rows(self, where: str = "1=1", params: tuple = ()) -> list[dict]:
        cur = self.conn.execute(f"SELECT * FROM audit WHERE {where} ORDER BY id", params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]

    def count_today(self, event: str, user_hash: str, tool: str) -> int:
        start = time.time() - 86400
        return self.conn.execute("SELECT COUNT(*) FROM audit WHERE event=? AND user_hash=? AND tool=? AND ts>? "
                                 "AND payload LIKE '%\"executed\": true%'", (event, user_hash, tool, start)).fetchone()[0]

    def register_thread(self, thread_id: str, tenant: str, user_hash: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO threads VALUES (?,?,?,?)", (thread_id, tenant, user_hash, time.time()))

    def threads_of(self, user_hash: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT thread_id FROM threads WHERE user_hash=?", (user_hash,))]

    def _erase(self, uh: str) -> int:
        with self._lock:
            self.conn.execute("UPDATE erasure_mode SET enabled=1")
            try:
                cur = self.conn.execute("UPDATE audit SET user_hash='erased', ticket_text=NULL WHERE user_hash=?", (uh,))
                self.conn.execute("UPDATE threads SET user_hash='erased' WHERE user_hash=?", (uh,))
                return cur.rowcount
            finally:
                self.conn.execute("UPDATE erasure_mode SET enabled=0")


@lru_cache
def get_audit() -> AuditLog:
    return AuditLog(settings.data_dir / "audit.sqlite")


def audit(event: str, **fields) -> None:
    get_audit().write(event, **fields)


def export_user(user_id: str, tenant: str, store=None) -> dict:
    """GDPR right of access: everything ATLAS holds about a user."""
    from atlas.agents.memory import prefs

    a = get_audit()
    uh = user_hash(user_id)
    return {"user_hash": uh, "audit": a.rows("user_hash=?", (uh,)), "threads": a.threads_of(uh),
            "prefs": prefs(store, tenant, uh) if store else {}}


def forget_user(user_id: str, tenant: str, *, checkpointer=None, store=None) -> dict:
    """GDPR right to erasure across EVERY store: checkpoints, memory store, audit identity fields.

    Also required in production (not local here): LangSmith trace masking/deletion, eval-dataset purge,
    vector index entries that quote the user. "We redact PII in logs" is not an erasure procedure.
    """
    from atlas.agents.memory import forget_user_memory

    a = get_audit()
    uh = user_hash(user_id)
    threads = a.threads_of(uh)
    if checkpointer is not None:
        for t in threads:
            checkpointer.delete_thread(t)
    mem = forget_user_memory(store, tenant, uh) if store is not None else 0
    rows = a._erase(uh)
    a.write("erasure", tenant=tenant, user_hash="erased", threads=len(threads), memory_items=mem, audit_rows=rows)
    return {"threads_deleted": len(threads), "memory_items_deleted": mem, "audit_rows_pseudonymized": rows}
