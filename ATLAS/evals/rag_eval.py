"""P2 — measure retrieval first. Four (+) configs, one golden set, one table, one decision.

    uv run python -m evals.rag_eval                       # all configs
    uv run python -m evals.rag_eval --configs dense hybrid
    uv run python -m evals.rag_eval --validate            # M2.5: every relevant key exists in the index

Decision rule: low recall → fix retrieval, don't touch the prompt. High recall + low faithfulness →
generation problem. High everything + unhappy users → the golden set doesn't match real queries.
"""

import argparse
import json
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from atlas.llm.budget import BudgetTracker
from atlas.rag.generate import answer, format_context
from atlas.rag.retrieve import CONFIGS, HybridRetriever
from atlas.rag.stores import Index
from evals.metrics import faithfulness_offline, hit_at_k, mean, mrr, p95, recall_at_k

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "evals/datasets/rag_golden_v1.jsonl"
RESULTS = ROOT / "evals/results"


def load_golden(path: Path = GOLDEN) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def validate(golden: list[dict], index: Index | None = None) -> list[str]:
    index = index or Index("main")
    keys = {(p["tenant"], p["key"]) for p in index.parents.data.values()}
    return [f"{r['id']}: {k}" for r in golden for k in r["relevant_keys"] if (r["tenant"], k) not in keys]


def run_config(name: str, golden: list[dict], *, generate: bool = True, role: str = "it_support") -> dict:
    r = HybridRetriever(CONFIGS[name])
    rows, lat, costs = [], [], []
    for g in golden:
        t0 = time.perf_counter()
        hits = r.retrieve(g["question"], g["tenant"], role)
        lat.append((time.perf_counter() - t0) * 1000)
        keys = [h.key for h in hits]
        row = {"id": g["id"], "type": g["type"], "keys": keys,
               "recall@5": recall_at_k(keys, g["relevant_keys"]), "hit@5": hit_at_k(keys, g["relevant_keys"]),
               "mrr": mrr(keys, g["relevant_keys"])}
        if generate:
            tracker = BudgetTracker(1.0, tags=["eval", f"rag:{name}"])
            hd = [h.as_dict() for h in hits]
            a = answer(g["question"], hd, callbacks=[tracker]) if hd else None
            costs.append(tracker.total_usd)
            row["answer"] = a.answer if a else ""
            row["faithfulness"] = faithfulness_offline(row["answer"], format_context(hd))
        rows.append(row)
    by_type = defaultdict(list)
    for row in rows:
        by_type[row["type"]].append(row["recall@5"])
    summary = {
        "config": name,
        "n": len(rows),
        "recall@5": mean(x["recall@5"] for x in rows),
        "hit@5": mean(x["hit@5"] for x in rows),
        "mrr": mean(x["mrr"] for x in rows),
        "faithfulness": mean(x["faithfulness"] for x in rows) if generate else None,
        "by_type": {k: mean(v) for k, v in sorted(by_type.items())},
        "p95_retrieval_ms": round(p95(lat), 1),
        "usd_per_query": round(mean(costs), 6) if costs else 0.0,
        "date": str(date.today()),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"rag_{name}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    return summary


def table(summaries: list[dict]) -> str:
    head = "| config | recall@5 | hit@5 | MRR | faithfulness | p95 ms | $/query |\n|---|---|---|---|---|---|---|"
    lines = [f"| {s['config']} | {s['recall@5']:.3f} | {s['hit@5']:.3f} | {s['mrr']:.3f} | "
             f"{(s['faithfulness'] or 0):.3f} | {s['p95_retrieval_ms']} | {s['usd_per_query']:.6f} |" for s in summaries]
    types = sorted({t for s in summaries for t in s["by_type"]})
    th = "\n\n| config | " + " | ".join(types) + " |\n|---|" + "---|" * len(types)
    tl = [f"| {s['config']} | " + " | ".join(f"{s['by_type'].get(t, 0):.2f}" for t in types) + " |" for s in summaries]
    return "\n".join([head, *lines]) + th + "\n" + "\n".join(tl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="*", default=["dense", "hybrid", "hybrid+rerank", "hybrid+rerank+mq"])
    ap.add_argument("--no-generate", action="store_true")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    golden = load_golden()
    from atlas.rag.retrieve import get_retriever

    get_retriever()  # ensures the main index exists
    if a.validate:
        missing = validate(golden)
        print("golden set OK" if not missing else "MISSING:\n" + "\n".join(missing))
        raise SystemExit(1 if missing else 0)
    summaries = [run_config(c, golden, generate=not a.no_generate) for c in a.configs]
    print(table(summaries))


if __name__ == "__main__":
    main()
