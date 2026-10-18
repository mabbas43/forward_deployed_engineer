"""P2: ask the knowledge base. Shows the retrieved sections (with scores) and the grounded answer.

    uv run python scripts/ask.py "What does error E-4471 mean?" [--config hybrid+rerank] [--tenant acme] [--role employee]
"""

import argparse

from atlas.rag.generate import answer
from atlas.rag.retrieve import CONFIGS, get_retriever

ap = argparse.ArgumentParser()
ap.add_argument("question")
ap.add_argument("--config", default=None, choices=list(CONFIGS))
ap.add_argument("--tenant", default="acme")
ap.add_argument("--role", default="employee")
a = ap.parse_args()
hits = get_retriever(a.config).retrieve(a.question, a.tenant, a.role)
for i, h in enumerate(hits, 1):
    print(f"{i}. [{h.score:>7}] {h.source}  §{h.section}{'  (superseded)' if h.status == 'superseded' else ''}")
print("\n" + answer(a.question, [h.as_dict() for h in hits]).answer)
