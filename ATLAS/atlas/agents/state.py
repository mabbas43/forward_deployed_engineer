"""P3 — state is the single source of truth. Nodes read it and return partial updates; reducers merge them.

Nothing lives in globals or closures — that's what makes runs resumable, inspectable, replayable, testable.
"""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages

Category = Literal["billing", "access", "bug", "hr", "other"]


TOOL_RESULTS_LIMIT = 50


def cap(existing: list | None, new: list | None) -> list:
    """Custom reducer (must be exactly (a, b) -> c): append, keep the last N — tool results must not grow
    without bound."""
    return ((existing or []) + (new or []))[-TOOL_RESULTS_LIMIT:]


class TicketState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    tool_results: Annotated[list[dict], cap]
    events: Annotated[list[str], operator.add]  # node sequence — seeds trajectory evals (P7)

    # identity — set by the API from the verified token, never by the model
    tenant: str
    user_id: str
    user_email: str
    user_role: str
    ticket_id: str
    ticket_text: str
    trace_id: str

    # P5 routing + memory
    route: dict
    recalled_cases: list[dict]
    avoid_cases: list[dict]
    procedures: list[str]
    prefs: dict

    # P3 core
    triage: dict
    context: list[dict]
    plan: list[str]
    critique: dict
    iterations: int
    approved: bool | None
    resolution: str
    citations: list[str]
    escalated: bool
    degraded: bool

    # P6 governance
    blocked: bool
    taint: bool
    guard_notes: list[str]
    pii_map: dict[str, str]  # pseudonym → real value; tools only (never prompts/logs/memory)
