"""P5 — semantic routing as data. The table (prompts/routes.v<N>.yaml) is versioned and promoted by the
registry (P7), so evals can change routing without a code change.

Embed the request → max cosine to each route's exemplars → best route above its min_score, else default.
"""

from functools import lru_cache

import numpy as np
import yaml

from atlas.config import ROOT
from atlas.rag.embeddings import embed


@lru_cache(maxsize=4)
def _load(version: int) -> tuple[list[dict], dict]:
    routes = yaml.safe_load((ROOT / f"prompts/routes.v{version}.yaml").read_text())
    return routes, {r["name"]: embed(r["examples"]) for r in routes}


def active_routes_version() -> int:
    from atlas.llm.prompts import active

    return int(active().get("routes", 1))


def route(text: str, version: int | None = None) -> dict:
    routes, ex = _load(version or active_routes_version())
    q = embed([text])[0]
    scored = [(float(np.max(ex[r["name"]] @ q)), r) for r in routes]
    score, best = max(scored, key=lambda t: t[0])
    default = next(r for r in routes if r["name"] == "ticket")
    chosen = best if score >= best.get("min_score", 0.75) else default
    return {"name": chosen["name"], "score": round(score, 3), "model": chosen.get("model"),
            "retrieval": chosen.get("retrieval"), "graph": chosen.get("graph"),
            "scores": {r["name"]: round(s, 3) for s, r in scored}}
