"""P5 — dynamic tool selection ("tool RAG"). 40 tools in context degrade selection accuracy and cost tokens.
Embed tool descriptions once; bind only the k most relevant per request. Measure accuracy at 40 vs k."""

import numpy as np

from atlas.rag.embeddings import embed


def select(query: str, tools: list, k: int = 6) -> list:
    if len(tools) <= k:
        return tools
    m = embed([f"{t.name}: {t.description}" for t in tools])
    q = embed([query])[0]
    order = np.argsort(-(m @ q))[:k]
    return [tools[i] for i in order]
