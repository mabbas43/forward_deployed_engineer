"""P2 — corrective RAG as a LangGraph loop: retrieve → grade → (rewrite → retrieve)* → answer, max 2 attempts.

Static "retrieve once" fails on multi-hop and vague questions. Grading + rewriting fixes a share of them;
the golden set's `type` column tells you which kinds.
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from atlas.llm import offline
from atlas.llm.prompts import load
from atlas.llm.providers import structured
from atlas.rag.generate import Answer, answer, format_context
from atlas.rag.rerank import toks
from atlas.rag.retrieve import get_retriever
from atlas.rag.rewrite import _map

MAX_ATTEMPTS = 2


class Grade(BaseModel):
    label: Literal["good", "poor"]


class Rewritten(BaseModel):
    query: str


class RagState(TypedDict, total=False):
    question: str
    query: str
    tenant: str
    role: str
    hits: list[dict]
    grade: str
    attempts: int
    answer: dict


def retrieve_node(s: RagState) -> dict:
    hits = get_retriever().retrieve(s.get("query") or s["question"], s["tenant"], s.get("role", "employee"))
    return {"hits": [h.as_dict() for h in hits], "attempts": s.get("attempts", 0) + 1}


def grade_node(s: RagState) -> dict:
    system, _ = load("grade")
    g = structured(Grade, "cheap").invoke(
        [("system", system),
         ("human", f"<question>\n{s['question']}\n</question>\n<context>\n{format_context(s['hits'])}\n</context>")])
    return {"grade": g.label}


def rewrite_node(s: RagState) -> dict:
    system, _ = load("rewrite")
    r = structured(Rewritten, "cheap").invoke(
        [("system", system), ("human", f"<question>\n{s['question']}\n</question>")])
    return {"query": r.query}


def answer_node(s: RagState) -> dict:
    return {"answer": answer(s["question"], s["hits"]).model_dump()}


def route(s: RagState) -> str:
    return "answer" if s["grade"] == "good" or s["attempts"] >= MAX_ATTEMPTS else "rewrite"


def build():
    g = StateGraph(RagState)
    g.add_node("retrieve", retrieve_node)
    g.add_node("grade", grade_node)
    g.add_node("rewrite", rewrite_node)
    g.add_node("answer", answer_node)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", route, ["answer", "rewrite"])
    g.add_edge("rewrite", "retrieve")
    g.add_edge("answer", END)
    return g.compile()


def ask(question: str, tenant: str = "acme", role: str = "employee") -> Answer:
    out = build().invoke({"question": question, "tenant": tenant, "role": role})
    return Answer(**out["answer"])


@offline.handles(Grade)
def _offline_grade(task: offline.Task) -> dict:
    q = set(toks(task.section("question")))
    ctx = set(toks(task.section("context")))
    return {"label": "good" if q and len(q & ctx) / len(q) >= 0.6 else "poor"}


@offline.handles(Rewritten)
def _offline_rewrite(task: offline.Task) -> dict:
    return {"query": _map(task.section("question"))}
