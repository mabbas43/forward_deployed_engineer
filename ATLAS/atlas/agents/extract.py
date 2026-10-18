"""P5 — background memory extractor (LangMem's pattern, hand-rolled).

Reads a finished thread, writes structured facts with a schema, a source trace id and a TTL.
Never persists raw PII: P6 redacts upstream, and the extractor refuses if its own output contains PII.
Run post-resolution (P8: as a queue job, never on the request path).
"""

import re

from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from atlas.agents.memory import _expires, put_prefs
from atlas.llm import offline
from atlas.llm.prompts import load
from atlas.llm.providers import structured


class Extraction(BaseModel):
    prefs: dict[str, str] = Field(default_factory=dict, description='e.g. {"language": "de", "channel": "teams"}')
    procedures: list[str] = Field(default_factory=list, description="Reusable tenant-level rules, imperative.")
    contains_pii: bool


def extract_and_store(store: BaseStore, thread: str, tenant: str, user_id: str, trace_id: str) -> Extraction:
    from atlas.governance.pii import contains

    system, _ = load("extract")
    x = structured(Extraction, "cheap").invoke([("system", system), ("human", f"<thread>\n{thread}\n</thread>")],
                                                config={"run_name": "extract"})
    blob = " ".join([*x.prefs.values(), *x.procedures])
    if x.contains_pii or contains(blob):
        return x  # store nothing rather than store PII
    if x.prefs:
        put_prefs(store, tenant, user_id, x.prefs, trace_id)
    for i, rule in enumerate(x.procedures):
        store.put((tenant, "procedures"), f"{trace_id}:{i}", {"rule": rule, "src": trace_id,
                                                               "expires": _expires("procedures")})
    return x


@offline.handles(Extraction)
def _offline_extract(task: offline.Task) -> dict:
    t = task.section("thread")
    low = t.lower()
    prefs = {}
    if re.search(r"\b(bitte|danke|ich|mein|nicht)\b", low):
        prefs["language"] = "de"
    if "teams" in low:
        prefs["channel"] = "teams"
    procs = []
    if "mfa" in low and "verif" in low:
        procs.append("Verify the user's identity by video call before resetting MFA.")
    if "e-4471" in low and "resolved" in low:
        procs.append("For scanner error E-4471, ask the user to log out and in again before escalating.")
    pii = bool(re.search(r"\+?\d[\d \-/]{7,}\d|DE\d{2}\s?\d{4}", t))
    return {"prefs": prefs, "procedures": procs, "contains_pii": pii}
