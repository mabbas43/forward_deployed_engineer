"""P2 M2.1: corpus size per tenant (docs, ~pages at 500 words/page, tokens)."""

from atlas.config import settings
from atlas.llm.tokens import count

for tdir in sorted(p for p in settings.corpus_dir.iterdir() if p.is_dir()):
    files = list(tdir.rglob("*.md"))
    text = "\n".join(f.read_text() for f in files)
    print(f"{tdir.name:>8}: {len(files):>4} docs  ~{len(text.split()) / 500:>6.1f} pages  {count(text):>8} tokens")
