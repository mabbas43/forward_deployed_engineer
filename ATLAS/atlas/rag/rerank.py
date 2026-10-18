"""P2 — rerankers. First-stage retrieval looks at query and doc *separately*; a reranker reads them *together*.

- LexicalReranker:  offline "cross-scorer" — idf-weighted overlap, exact identifier bonus, section-title match
- CrossEncoderReranker: sentence-transformers cross-encoder (`uv sync --extra rerank`)
- LLMReranker: listwise reranking by an LLM — strong, slow, expensive; a ceiling to compare against
"""

import math
import re
from collections import Counter

from pydantic import BaseModel, Field

TOK = re.compile(r"[a-z0-9äöüß][a-z0-9äöüß\-]*")
CODE = re.compile(r"\b[a-z]{1,4}-\d{2,}\b")
STOP = set("a an the of to in on for is are be was do does how what which who when where why i my me we our "
           "you your it its and or with from at by can get after before this that there not should would could will "
           "need want please help any some about also just like".split())


def toks(s: str) -> list[str]:
    return [t for t in TOK.findall(s.lower()) if t not in STOP and len(t) > 1]


class LexicalReranker:
    name = "lexical"

    def __call__(self, query: str, cands: list[tuple[str, str, str]]) -> list[tuple[str, float]]:
        """cands = [(id, text, section)] → [(id, score)] sorted desc."""
        q = toks(query)
        if not q or not cands:
            return [(c[0], 0.0) for c in cands]
        df = Counter(t for _, text, _ in cands for t in set(toks(text)))
        n = len(cands)
        codes = set(CODE.findall(query.lower()))
        out = []
        for id_, text, section in cands:
            dt = Counter(toks(text))
            s = sum((1 + math.log(dt[t])) * math.log(1 + n / (1 + df[t])) for t in set(q) if dt[t])
            s += 3.0 * sum(1 for c in codes if c in text.lower())
            s += 1.5 * len(set(q) & set(toks(section)))
            bigrams = {" ".join(q[i : i + 2]) for i in range(len(q) - 1)}
            s += 0.5 * sum(1 for b in bigrams if b in " ".join(toks(text)))
            out.append((id_, s / (1 + 0.002 * len(text))))
        return sorted(out, key=lambda x: -x[1])


class CrossEncoderReranker:
    name = "cross"

    def __init__(self, model: str = "BAAI/bge-reranker-base"):
        from sentence_transformers import CrossEncoder  # optional extra

        self.model = CrossEncoder(model)

    def __call__(self, query, cands):
        scores = self.model.predict([(query, t) for _, t, _ in cands])
        return sorted(((c[0], float(s)) for c, s in zip(cands, scores, strict=True)), key=lambda x: -x[1])


class Ranking(BaseModel):
    order: list[int] = Field(description="Passage numbers from most to least relevant to the question.")


class LLMReranker:
    name = "llm"

    def __call__(self, query, cands):
        from atlas.config import settings
        from atlas.llm.providers import structured

        if not settings.online:
            return LexicalReranker()(query, cands)
        listing = "\n".join(f"[{i}] {t[:600]}" for i, (_, t, _) in enumerate(cands))
        r = structured(Ranking, "cheap").invoke(
            [("system", "Rank the passages by how well they answer the question."),
             ("human", f"<question>\n{query}\n</question>\n<passages>\n{listing}\n</passages>")])
        seen = [i for i in r.order if 0 <= i < len(cands)]
        seen += [i for i in range(len(cands)) if i not in seen]
        return [(cands[i][0], float(len(seen) - rank)) for rank, i in enumerate(seen)]


def get_reranker(kind: str):
    if kind == "none":
        return None
    if kind == "cross":
        try:
            return CrossEncoderReranker()
        except Exception:
            return LexicalReranker()
    if kind == "llm":
        return LLMReranker()
    return LexicalReranker()
