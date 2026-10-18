"""Shared eval metrics. Retrieval metrics you write yourself (20 lines); generation metrics use a judge."""

import re
import statistics

from atlas.rag.rerank import toks


def recall_at_k(retrieved: list[str], relevant: list[str], k: int = 5) -> float:
    return len(set(retrieved[:k]) & set(relevant)) / len(relevant) if relevant else 0.0


def hit_at_k(retrieved: list[str], relevant: list[str], k: int = 5) -> float:
    return float(bool(set(retrieved[:k]) & set(relevant)))


def mrr(retrieved: list[str], relevant: list[str]) -> float:
    for i, r in enumerate(retrieved):
        if r in relevant:
            return 1 / (i + 1)
    return 0.0


def p95(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=20)[-1] if len(xs) >= 2 else (xs[0] if xs else 0.0)


def mean(xs) -> float:
    xs = list(xs)
    return round(sum(xs) / len(xs), 4) if xs else 0.0


CITE = re.compile(r"\[[^\]]+\]")


def faithfulness_offline(answer: str, context: str) -> float:
    """Share of answer sentences supported by some context sentence (token overlap ≥ 0.5, and every number in it appears in the context).

    A crude, deterministic stand-in for RAGAS faithfulness (claim extraction + LLM verification).
    Read RAGAS's prompts to understand what the real metric does before trusting either.
    """
    if not answer.strip() or "can't find" in answer.lower():
        return 1.0  # abstaining is faithful
    ctx_sents = [set(toks(s)) for s in re.split(r"(?<=[.!?])\s+|\n+", context) if s.strip()]
    sents = [s for s in re.split(r"(?<=[.!?])\s+|;\s*", CITE.sub("", answer)) if len(toks(s)) >= 3]
    if not sents:
        return 1.0
    ctx_all = set().union(*ctx_sents) if ctx_sents else set()
    ok = 0
    for s in sents:
        st = set(toks(s))
        numbers = {t for t in st if any(ch.isdigit() for ch in t)}
        if numbers - ctx_all:
            continue  # a number the context never states is a hallucination, however similar the wording
        if any(len(st & c) / len(st) >= 0.5 for c in ctx_sents if c):
            ok += 1
    return ok / len(sents)
