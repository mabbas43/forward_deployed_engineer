"""P2 — hybrid retrieval: dense + BM25 → Reciprocal Rank Fusion → rerank → parent expansion.

Dense captures meaning and misses strings (E-4471, names, SKUs). BM25 nails strings and misses paraphrase.
Run both; fuse with RRF (score = Σ 1/(k + rank), k≈60 — no tuning). Tenant and access filters apply INSIDE
both retrievers, never after. Rerank top-20 → top-5. Return parents, deduplicated.

    uv run python scripts/ask.py "What does error E-4471 mean?"
"""

from dataclasses import asdict, dataclass, field
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from atlas.logging import get_logger
from atlas.rag.embeddings import embed
from atlas.rag.rerank import get_reranker, toks
from atlas.rag.stores import Index

log = get_logger()

# Access-aware retrieval: which document access levels each role may read. (P6 cites the test for this.)
ROLE_ACCESS = {
    "employee": {"employee"},
    "helpdesk": {"employee", "helpdesk"},
    "it_support": {"employee", "helpdesk", "it_admin"},
}


def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    s: dict[str, float] = {}
    for r in rankings:
        for rank, id_ in enumerate(r):
            s[id_] = s.get(id_, 0.0) + 1.0 / (k + rank)
    return sorted(s, key=lambda i: -s[i])


@dataclass
class Hit:
    id: str
    parent_id: str
    key: str
    source: str
    title: str
    section: str
    text: str
    score: float
    status: str = "current"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetrievalConfig:
    name: str
    dense: bool = True
    sparse: bool = True
    rerank: str = "lexical"  # none | lexical | cross | llm
    rewrite: str | None = None  # None | mq | hyde
    freshness: bool = True
    index: str = "main"
    k_first: int = 20
    k_final: int = 5
    extra: dict = field(default_factory=dict)


CONFIGS = {
    "dense": RetrievalConfig("dense", sparse=False, rerank="none", freshness=False),
    "hybrid": RetrievalConfig("hybrid", rerank="none", freshness=False),
    "hybrid+rerank": RetrievalConfig("hybrid+rerank"),
    "hybrid+rerank+mq": RetrievalConfig("hybrid+rerank+mq", rewrite="mq"),
    "hybrid+rerank+hyde": RetrievalConfig("hybrid+rerank+hyde", rewrite="hyde"),
    "contextual": RetrievalConfig("contextual", index="contextual"),
    # P6 drill: the main corpus PLUS a poisoned document (data/redteam_docs/) — never serve this.
    "redteam": RetrievalConfig("redteam", index="redteam"),
}


class BM25Index:
    """Per-tenant BM25. In-memory — at 50k docs, move to OpenSearch/pgvector+tsvector (see checkpoint Q4)."""

    def __init__(self, index: Index):
        self.v = index.vectors
        self._by_tenant: dict[str, tuple[BM25Okapi, list[str]]] = {}

    def _build(self, tenant: str):
        ids = [i for i in self.v.ids if self.v.metas[i]["tenant"] == tenant]
        corpus = [toks(self.v.texts[i]) or ["_"] for i in ids]
        self._by_tenant[tenant] = (BM25Okapi(corpus) if corpus else None, ids)

    def top(self, query: str, k: int, tenant: str, access: set[str]) -> list[str]:
        if tenant not in self._by_tenant:
            self._build(tenant)
        bm, ids = self._by_tenant[tenant]
        if bm is None:
            return []
        scores = np.asarray(bm.get_scores(toks(query) or ["_"]))
        allowed = np.array([self.v.metas[i]["access_level"] in access for i in ids])
        scores[~allowed] = -np.inf
        order = np.argsort(-scores)[:k]
        return [ids[i] for i in order if np.isfinite(scores[i]) and scores[i] > 0]


class HybridRetriever:
    def __init__(self, cfg: RetrievalConfig, index: Index | None = None):
        self.cfg = cfg
        self.index = index or Index(cfg.index)
        self.bm = BM25Index(self.index)
        self.rr = get_reranker(cfg.rerank)

    def _queries(self, query: str) -> list[str]:
        if self.cfg.rewrite == "mq":
            from atlas.rag.rewrite import multi_query

            return [query, *multi_query(query)]
        if self.cfg.rewrite == "hyde":
            from atlas.rag.rewrite import hyde

            return [query, *hyde(query)]
        return [query]

    def retrieve(self, query: str, tenant: str, role: str = "employee", *, k_final: int | None = None) -> list[Hit]:
        cfg, v = self.cfg, self.index.vectors
        k_final = k_final or cfg.k_final
        access = ROLE_ACCESS.get(role, {"employee"})
        flt = {"tenant": tenant, "access_level": list(access)}
        lists: list[list[str]] = []
        queries = self._queries(query)
        if cfg.dense:
            qv = embed(queries)
            for row in qv:
                lists.append([i for i, _ in v.search(row, cfg.k_first, flt)])
        if cfg.sparse:
            for q in queries:
                lists.append(self.bm.top(q, cfg.k_first, tenant, access))
        fused = rrf(lists)[: cfg.k_first]
        if self.rr and fused:
            ranked = self.rr(query, [(i, v.texts[i], v.metas[i]["section"]) for i in fused])
        else:
            ranked = [(i, 1.0 / (60 + r)) for r, i in enumerate(fused)]
        if cfg.freshness:  # prefer current documents over superseded drafts (stable sort keeps rank order)
            ranked = sorted(ranked, key=lambda x: v.metas[x[0]].get("status") == "superseded")
        seen, out = set(), []
        for i, score in ranked:
            m = v.metas[i]
            if m["parent_id"] in seen:
                continue
            seen.add(m["parent_id"])
            parent = self.index.parents.get(m["parent_id"], {})
            out.append(Hit(i, m["parent_id"], m["key"], m["source"], m["title"], m["section"],
                           parent.get("text", v.texts[i]), round(float(score), 4), m.get("status", "current")))
            if len(out) == k_final:
                break
        log.info("retrieve", config=cfg.name, tenant=tenant, role=role, n=len(out),
                 keys=[h.key for h in out])
        return out


@lru_cache(maxsize=8)
def get_retriever(config: str | None = None) -> HybridRetriever:
    """The serving retriever. Config comes from prompts/active.yaml (`retrieval:`), so P7 can promote changes."""
    from atlas.llm.prompts import active

    name = config or active().get("retrieval", "hybrid+rerank")
    r = HybridRetriever(CONFIGS[name])
    if len(r.index.vectors) == 0:  # first run: build the index from data/corpus
        from atlas.rag.ingest import ingest_corpus

        extra = None
        if r.cfg.index == "redteam":
            from atlas.config import ROOT

            extra = [(p, "acme") for p in sorted((ROOT / "data/redteam_docs").glob("*.md"))]
        ingest_corpus(index_name=r.cfg.index, contextual=r.cfg.index == "contextual", extra=extra)
        r = HybridRetriever(CONFIGS[name])
    return r
