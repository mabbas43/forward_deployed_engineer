"""P2 — query rewriting closes the vocabulary gap between how users ask and how docs are written.

multi_query: 3 paraphrases → retrieve each → RRF.   hyde: draft a hypothetical answer, search with *that*.
Both are one structured-output call. Measure; keep only what moves recall.
"""

from pydantic import BaseModel, Field

from atlas.llm import offline
from atlas.llm.prompts import load
from atlas.llm.providers import structured
from atlas.rag.rerank import toks


class Paraphrases(BaseModel):
    queries: list[str] = Field(min_length=3, max_length=3, description="Three alternative phrasings.")


class Hypothetical(BaseModel):
    answer: str = Field(description="A short passage that would answer the question in a company document.")


def multi_query(q: str) -> list[str]:
    system, _ = load("rewrite")
    return structured(Paraphrases, "cheap").invoke(
        [("system", system), ("human", f"<question>\n{q}\n</question>")], config={"run_name": "multi_query"}).queries


def hyde(q: str) -> list[str]:
    system, _ = load("hyde")
    return [structured(Hypothetical, "cheap").invoke(
        [("system", system), ("human", f"<question>\n{q}\n</question>")], config={"run_name": "hyde"}).answer]


# ---- offline heuristics: map user vocabulary → document vocabulary --------------------------------------

DOC_VOCAB = {
    "locked out": "account lockout failed sign-in attempts",
    "log in": "sign in authentication",
    "login": "sign in authentication",
    "vacation": "annual leave vacation days",
    "holiday": "annual leave vacation days",
    "time off": "annual leave",
    "charged twice": "duplicate charge invoice paid twice credit note",
    "paid twice": "duplicate charge credit note",
    "new phone": "MFA registration new phone authenticator",
    "changed phones": "MFA registration new phone authenticator",
    "from home": "remote access VPN GlobalProtect",
    "abroad": "working from abroad EU/EEA approval",
    "blue screen": "blue screen after Windows update safe mode",
    "clicked": "phishing link security incident hotline",
    "expenses": "expense report reimbursement receipts",
    "printer": "office printers follow-me printing",
    "scanner": "handheld scanner WMS error",
    "baby": "parental leave Elternzeit",
    "password": "password requirements reset",
}


def _map(q: str) -> str:
    low = q.lower()
    extra = [v for k, v in DOC_VOCAB.items() if k in low]
    return " ".join([q, *extra])


@offline.handles(Paraphrases)
def _offline_paraphrases(task: offline.Task) -> dict:
    q = task.section("question")
    keys = " ".join(toks(q))
    mapped = _map(q)
    return {"queries": [mapped, f"company policy {keys}", keys or q]}


@offline.handles(Hypothetical)
def _offline_hyde(task: offline.Task) -> dict:
    q = task.section("question")
    return {"answer": f"According to the internal policy on {' '.join(toks(q))}: {_map(q)}. "
                      "Employees should follow the documented procedure and contact the Service Desk if it fails."}
