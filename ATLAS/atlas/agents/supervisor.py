"""P5 — supervisor + specialists, handoffs via Command. Only when earned.

The supervisor routes to a specialist subgraph with a *compact brief*, not the transcript. Each specialist
has its own tool subset (least privilege) and can be evaluated separately — the main reason to split.
Multi-agent adds coordination cost and failure modes; earn it with a measured need.
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field

from atlas.agents.plan import make_plan
from atlas.agents.tools import BY_NAME, DOMAINS
from atlas.llm import offline
from atlas.llm.offline import has_any
from atlas.llm.prompts import load
from atlas.llm.providers import structured


class Decision(BaseModel):
    specialist: Literal["access", "billing", "respond"]
    brief: str = Field(description="Max two sentences for the specialist.")


class SupState(TypedDict, total=False):
    ticket_text: str
    user_email: str
    tenant: str
    triage: dict
    context: list[dict]
    brief: str
    specialist: str
    plan: list[str]


def supervisor(s: SupState) -> Command[Literal["access", "billing", "respond"]]:
    system, _ = load("supervisor")
    d = structured(Decision, "cheap").invoke(
        [("system", system), ("human", f"<ticket>\n{s['ticket_text']}\n</ticket>\n<triage>\n{s.get('triage')}\n</triage>")])
    return Command(goto=d.specialist, update={"brief": d.brief, "specialist": d.specialist})


def _specialist(domain: str):
    tools = [BY_NAME[n] for n in sorted(DOMAINS[domain])]

    def node(s: SupState) -> dict:
        state = {**s, "ticket_text": f"{s['ticket_text']}\n(brief: {s.get('brief', '')})"}
        return {"plan": make_plan(state, tools).steps}

    # A real specialist is a compiled subgraph with its own scoped state; one node keeps the example readable.
    g = StateGraph(SupState)
    g.add_node("plan", node)
    g.add_edge(START, "plan")
    g.add_edge("plan", END)
    return g.compile()


def respond(s: SupState) -> dict:
    return {"plan": ["ANSWER: Answer from the retrieved company documents."]}


def build():
    g = StateGraph(SupState)
    g.add_node("supervisor", supervisor, destinations=("access", "billing", "respond"))
    g.add_node("access", _specialist("access"))
    g.add_node("billing", _specialist("billing"))
    g.add_node("respond", respond)
    g.add_edge(START, "supervisor")
    for n in ("access", "billing", "respond"):
        g.add_edge(n, END)
    return g.compile()


@offline.handles(Decision)
def _offline_decision(task: offline.Task) -> dict:
    t = task.section("ticket")
    tri = task.section("triage")
    if "'billing'" in tri or has_any(t, ["invoice", "payment", "refund", "paid twice"]):
        return {"specialist": "billing", "brief": "Billing issue; check the invoice and payments."}
    if "'access'" in tri or has_any(t, ["password", "locked", "mfa", "access", "login"]):
        return {"specialist": "access", "brief": "Access issue; verify the account before any write."}
    return {"specialist": "respond", "brief": "Answer from documents or escalate."}
