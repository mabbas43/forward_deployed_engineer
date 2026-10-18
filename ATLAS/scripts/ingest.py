"""P2: (re)build an index. Idempotent and incremental — run it twice and watch `skipped`.

    uv run python scripts/ingest.py [--index main] [--contextual]
"""

import argparse
import json

from atlas.rag.ingest import ingest_corpus

ap = argparse.ArgumentParser()
ap.add_argument("--index", default="main")
ap.add_argument("--contextual", action="store_true", help="Anthropic-style contextual chunk prefixes")
a = ap.parse_args()
print(json.dumps(ingest_corpus(index_name=a.index, contextual=a.contextual), indent=2))
