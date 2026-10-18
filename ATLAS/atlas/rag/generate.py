"""P2 — grounded generation. Answer only from context, cite sources, or say you can't.

Evaluate retrieval and generation separately: low recall → fix retrieval (don't touch this prompt);
high recall + low faithfulness → fix this step.
"""

import re

from pydantic import BaseModel, Field

from atlas.llm import offline
from atlas.llm.prompts import load
from atlas.llm.providers import run_config as _cfg
from atlas.llm.providers import structured
from atlas.rag.rerank import toks

NOT_FOUND = "I can't find this in the company documents."


class Answer(BaseModel):
    answer: str = Field(description="The answer, with [source] citations, or the exact not-found sentence.")
    citations: list[str] = Field(default_factory=list, description="Sources cited, e.g. ['acme/it/vpn-guide.md'].")
    answerable: bool = Field(description="False if the context does not contain the answer.")


def format_context(hits: list[dict]) -> str:
    """Passages are delimited and labelled as data — part of the indirect-injection defence (P6)."""
    return "\n\n".join(f"[{h['source']}] ({h['section']})\n{h['text']}" for h in hits)


def answer(question: str, hits: list[dict], callbacks: list | None = None) -> Answer:
    system, _ = load("answer")
    return structured(Answer, "primary").invoke(
        [("system", system),
         ("human", f"<question>\n{question}\n</question>\n<context>\n{format_context(hits)}\n</context>")],
        config=_cfg("answer", callbacks))


# ---- offline heuristic: extractive answer from the best-matching sentences --------------------------------

SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def best_sentences(question: str, context: str, n: int = 2) -> list[tuple[str, str, float]]:
    """Return [(sentence, source, score)] — sentences with the highest question-term overlap.

    A sentence's section heading counts as evidence (a sentence under "Connecting from home" is about that),
    and an exact identifier match (E-4471, INV-88231) counts double — the same intuitions as BM25 + headings.
    """
    from atlas.rag.rerank import CODE

    q = set(toks(question))
    codes = set(CODE.findall(question.lower()))
    out = []
    source, section = "", ""
    for line in context.splitlines():
        m = re.match(r"^\[([^\]]+)\](?: \(([^)]*)\))?", line)
        if m:
            source, section = m.group(1), m.group(2) or ""
            continue
        for s in SENT.split(line):
            s = s.strip(" |-")
            if len(s) < 12 or s.startswith("#"):
                continue
            st = set(toks(s)) | set(toks(section))
            overlap = len(q & st) + sum(1 for c in codes if c in s.lower())
            if len(q) >= 3 and overlap < 2:  # one shared word is coincidence, not relevance
                continue
            out.append((s, source, overlap / (1 + len(q))))
    return sorted(out, key=lambda x: -x[2])[:n]


@offline.handles(Answer)
def _offline_answer(task: offline.Task) -> dict:
    q, ctx = task.section("question"), task.section("context")
    best = best_sentences(q, ctx)
    if not best or best[0][2] < 0.2:
        return {"answer": NOT_FOUND, "citations": [], "answerable": False}
    cites = sorted({src for _, src, _ in best if src})
    top = best[0][0]
    if "|" in top:  # matched a table header: answer with the table rows, not the header alone
        lines = ctx.splitlines()
        idx = next((i for i, ln in enumerate(lines) if top in ln.strip(" |")), None)
        if idx is not None:
            rows = [ln.strip() for ln in lines[idx + 1 : idx + 8] if ln.strip().startswith("|") and "---" not in ln]
            return {"answer": f"{top}: " + "; ".join(r.strip("| ").replace(" | ", ": ", 1) for r in rows)
                    + f" [{best[0][1]}]", "citations": [best[0][1]], "answerable": True}
    text = " ".join(f"{s} [{src}]" for s, src, _ in best)
    return {"answer": text, "citations": cites, "answerable": True}
