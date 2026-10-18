"""P5 — memory on the LangGraph Store.

| Type        | What                              | Where                          | Written by           |
|-------------|-----------------------------------|--------------------------------|----------------------|
| working     | current context + graph state     | TicketState                    | nodes                |
| short-term  | this thread's history             | checkpointer                   | graph                |
| semantic    | durable facts about a user        | (tenant, user, "prefs")        | background extractor |
| episodic    | specific past cases + outcomes    | (tenant, "cases")              | feedback endpoint    |
| procedural  | learned rules                     | (tenant, "procedures")         | extractor/optimizer  |

Namespaces are a security boundary: every read and write carries the tenant. A cross-namespace read is a breach.
Write policy beats read policy: cases are written at resolution *with a rating*, never after every turn.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel

from atlas.config import settings
from atlas.rag.embeddings import DIMS, get_embeddings

RETENTION_DAYS = {"cases": 365, "prefs": 180, "procedures": 180}  # P6: mirrored in governance/policy.yaml


def _index() -> dict:
    return {"embed": get_embeddings(), "dims": DIMS if get_embeddings().__class__.__name__ == "HashingEmbeddings"
            else 1536, "fields": ["ticket", "rule"]}


def memory_store() -> BaseStore:
    """In-process store with semantic search — tests and the adaptive-curve experiment."""
    return InMemoryStore(index=_index())


@lru_cache
def get_store() -> BaseStore:
    """Persistent dev store (SQLite + sqlite-vec). Production: PostgresStore (uv sync --extra infra)."""
    from langgraph.store.sqlite import SqliteStore

    conn = sqlite3.connect(settings.data_dir / "store.sqlite", check_same_thread=False, isolation_level=None)
    st = SqliteStore(conn, index=_index())
    st.setup()
    return st


def _expires(kind: str) -> str:
    return (datetime.now(UTC) + timedelta(days=RETENTION_DAYS[kind])).isoformat()


class Case(BaseModel):
    ticket: str
    plan: list[str]
    outcome: str
    rating: int
    route: str = "ticket"
    trace_id: str = ""
    resolved_by: str = "atlas"  # atlas | human


def remember_case(store: BaseStore, tenant: str, ticket_id: str, case: Case) -> None:
    store.put((tenant, "cases"), ticket_id, {**case.model_dump(), "expires": _expires("cases")})


def recall_cases(store: BaseStore, tenant: str, ticket: str, k: int = 3, min_rating: int = 4):
    """Top-k well-rated similar cases as positive few-shots, plus one low-rated case as an explicit 'avoid'.
    Low-rated cases are NEVER used as positives."""
    hits = store.search((tenant, "cases"), query=ticket, limit=k * 3)
    good = [h.value for h in hits if h.value.get("rating", 0) >= min_rating][:k]
    avoid = [h.value for h in hits if h.value.get("rating", 0) <= 2][:1]
    return good, avoid


def procedures(store: BaseStore, tenant: str, ticket: str, k: int = 3) -> list[str]:
    return [h.value["rule"] for h in store.search((tenant, "procedures"), query=ticket, limit=k)]


def prefs(store: BaseStore, tenant: str, user_id: str) -> dict:
    it = store.get((tenant, user_id, "prefs"), "profile")
    return {k: v for k, v in (it.value if it else {}).items() if k not in {"src", "expires"}}


def put_prefs(store: BaseStore, tenant: str, user_id: str, new: dict, src: str) -> None:
    store.put((tenant, user_id, "prefs"), "profile",
              {**prefs(store, tenant, user_id), **new, "src": src, "expires": _expires("prefs")})


def purge_expired(store: BaseStore, tenant: str) -> int:
    """Retention: delete items past their `expires`. Run daily (P8: a scheduled job)."""
    now, n = datetime.now(UTC).isoformat(), 0
    for ns in store.list_namespaces(prefix=(tenant,)):
        for it in store.search(ns, limit=10_000):
            if it.value.get("expires", "9999") < now:
                store.delete(ns, it.key)
                n += 1
    return n


def forget_user_memory(store: BaseStore, tenant: str, user_id: str) -> int:
    """GDPR erasure for the store: every namespace under (tenant, user_id, ...)."""
    n = 0
    for ns in store.list_namespaces(prefix=(tenant, user_id)):
        for it in store.search(ns, limit=10_000):
            store.delete(ns, it.key)
            n += 1
    return n
