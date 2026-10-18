"""P2 M2.1: grow the corpus toward 200+ pages. Online: an LLM writes realistic, messy docs from a schema of doc
types (duplicates, stale drafts, tables). Offline: deterministic variants so the pipeline has volume to chew on.

    uv run python scripts/generate_corpus.py --n 40 --tenant acme
Review generated docs before adding questions about them to the golden set.
"""

import argparse
import random

from pydantic import BaseModel

from atlas.config import settings

TYPES = ["IT runbook", "HR policy", "warehouse SOP", "finance procedure", "security standard", "past ticket notes"]
TOPICS = ["printer fleet", "forklift tablets", "SAP role changes", "travel booking", "laptop encryption",
          "guest Wi-Fi", "shift handover", "data retention", "badge access", "home office equipment"]


class Doc(BaseModel):
    title: str
    markdown: str


def offline_doc(i: int, rnd: random.Random) -> Doc:
    typ, topic = rnd.choice(TYPES), rnd.choice(TOPICS)
    code = f"E-{rnd.randint(7000, 7999)}"
    body = (f"# {topic.title()} — {typ}\n\n## Purpose\nThis {typ.lower()} describes how Acme Logistics handles "
            f"{topic}.\n\n## Procedure\n1. Check the {topic} status in the Service Portal.\n2. If error {code} "
            f"appears, restart the device and retry.\n3. Escalate to the Service Desk after two failed attempts.\n\n"
            f"## Contacts\n| Role | Contact |\n|---|---|\n| Owner | {rnd.choice(['IT Ops', 'HR', 'Finance'])} |\n"
            f"| Escalation | Service Desk ext. {rnd.randint(4000, 4999)} |\n")
    return Doc(title=f"{topic}-{i}", markdown=body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--tenant", default="acme")
    a = ap.parse_args()
    out = settings.corpus_dir / a.tenant / "generated"
    out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(42)
    for i in range(a.n):
        if settings.online:
            from atlas.llm.providers import structured

            d = structured(Doc, "cheap").invoke([("system", "Write a realistic internal company document in Markdown "
                                                  "with front-matter-free headers (#, ##), one table, specific numbers."),
                                                 ("human", f"Type: {rnd.choice(TYPES)}. Topic: {rnd.choice(TOPICS)}.")])
        else:
            d = offline_doc(i, rnd)
        meta = "---\ntitle: " + d.title + "\neffective_from: 2026-06-01\nowner: generated\naccess_level: employee\n---\n"
        (out / f"{d.title.lower().replace(' ', '-')}.md").write_text(meta + d.markdown)
    print(f"wrote {a.n} docs to {out} — now run scripts/ingest.py")


if __name__ == "__main__":
    main()
