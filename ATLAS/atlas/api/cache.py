"""P8 — caching, three layers, and the keys that make them safe.

Exact cache (FAQ route): key = (tenant, prompt_version, retrieval_version, normalized query).
Semantic cache: same key parts + query embedding; serve above a STRICT threshold; every hit is audited and
sampled into online eval (a confidently wrong cached answer is the worst failure mode).
Provider prompt caching: keep the system prompt a stable prefix — measure hit rate and savings.
Forgetting the prompt version in the key = serving answers from a prompt you rolled back.
"""

import re
import time

import numpy as np

from atlas.governance.audit import audit
from atlas.rag.embeddings import embed


def normalize(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", "", q.lower())).strip()


def version_key(tenant: str) -> str:
    from atlas.llm.prompts import active

    a = active()
    return f"{tenant}:answer.v{a['prompts']['answer']}:{a.get('retrieval')}"


class ExactCache:
    def __init__(self, ttl: float = 7 * 86400):
        self.ttl, self.d = ttl, {}

    def get(self, tenant: str, q: str):
        hit = self.d.get((version_key(tenant), normalize(q)))
        if hit and hit[0] > time.time():
            audit("cache_hit", tenant=tenant, kind="exact")
            return hit[1]
        return None

    def put(self, tenant: str, q: str, value):
        self.d[(version_key(tenant), normalize(q))] = (time.time() + self.ttl, value)


class SemanticCache:
    def __init__(self, threshold: float = 0.93, ttl: float = 7 * 86400):
        self.threshold, self.ttl = threshold, ttl
        self.entries: dict[str, list[tuple[np.ndarray, object, float, str]]] = {}

    def get(self, tenant: str, q: str):
        key = version_key(tenant)
        rows = [r for r in self.entries.get(key, []) if r[2] > time.time()]
        if not rows:
            return None
        v = embed([q])[0]
        sims = [float(r[0] @ v) for r in rows]
        i = int(np.argmax(sims))
        if sims[i] >= self.threshold:
            audit("cache_hit", tenant=tenant, kind="semantic", score=round(sims[i], 3), cached_query=rows[i][3][:80])
            return rows[i][1]
        return None

    def put(self, tenant: str, q: str, value):
        self.entries.setdefault(version_key(tenant), []).append((embed([q])[0], value, time.time() + self.ttl, q))
