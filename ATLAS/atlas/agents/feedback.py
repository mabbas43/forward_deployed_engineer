"""P5 — the feedback loop: ratings become episodic memory; finished threads feed the background extractor.

Write policy: cases are stored at resolution *with a rating*. Human-corrected resolutions are stored as
high-rated cases (resolved_by="human") — that's how the agent learns approaches it couldn't find itself.
"""

from langgraph.store.base import BaseStore

from atlas.agents.extract import extract_and_store
from atlas.agents.memory import Case, remember_case
from atlas.governance.audit import audit, user_hash


def record_feedback(store: BaseStore, state: dict, rating: int, *, corrected_plan: list[str] | None = None,
                    run_extractor: bool = True) -> Case:
    plan = corrected_plan or state.get("plan", [])
    case = Case(ticket=state["ticket_text"], plan=plan, outcome=state.get("resolution", "")[:500],
                rating=5 if corrected_plan else rating, route=(state.get("route") or {}).get("name", "ticket"),
                trace_id=state.get("trace_id", ""), resolved_by="human" if corrected_plan else "atlas")
    remember_case(store, state["tenant"], state["ticket_id"], case)
    audit("feedback", trace_id=state.get("trace_id"), tenant=state["tenant"], rating=rating,
          corrected=bool(corrected_plan))
    if run_extractor:
        thread = f"{state['ticket_text']}\n---\n{state.get('resolution', '')}"
        extract_and_store(store, thread, state["tenant"], user_hash(state.get("user_id", "anon")),
                          state.get("trace_id", state["ticket_id"]))
    return case
