"""P7 — change management: shadow → canary → promote → watch → (rollback).

shadow(): run the candidate alongside the active config on the same tickets; serve active, log both, judge
pairwise; report the candidate's win rate. canary: `variant_for()` deterministically routes N% of tickets to
the candidate (the API reads it); compare online metrics + $/ticket before calling registry.promote().

    uv run python -m atlas.ops.rollout shadow prompts.triage=2
"""

import hashlib
import json
import sys
from pathlib import Path

from atlas.config import ROOT


def variant_for(ticket_id: str, canary_pct: int) -> str:
    """Stable assignment: the same ticket always gets the same variant (retries stay consistent)."""
    bucket = int(hashlib.sha256(ticket_id.encode()).hexdigest()[:8], 16) % 100
    return "candidate" if bucket < canary_pct else "active"


def _score(case: dict, row: dict) -> float:
    from evals.judges import CODE_EVALS, grounded

    vals = [ev(row["inputs"], case, row["expected"])["score"] for ev in [*CODE_EVALS, grounded]]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals)


def shadow(overrides: dict, limit: int = 30) -> dict:
    """Pairwise comparison on the golden set: wins / ties / losses for the candidate."""
    from langgraph.checkpoint.memory import InMemorySaver

    from atlas.agents.memory import memory_store
    from atlas.agents.ticket_graph import build
    from evals.run import apply_overrides, load, run_case

    rows = load("golden_v1.jsonl")[:limit]
    active_cases = [run_case(build(InMemorySaver(), memory_store()), r) for r in rows]
    apply_overrides(overrides)
    cand_cases = [run_case(build(InMemorySaver(), memory_store()), {**r, "id": r["id"] + "-cand"}) for r in rows]
    w = t = lo = 0
    diffs = []
    for r, a, c in zip(rows, active_cases, cand_cases, strict=True):
        sa, sc = _score(a, r), _score(c, r)
        if sc > sa:
            w += 1
            diffs.append({"id": r["id"], "winner": "candidate"})
        elif sc < sa:
            lo += 1
            diffs.append({"id": r["id"], "winner": "active"})
        else:
            t += 1
    usd_a = sum(x["usd"] for x in active_cases) / len(rows)
    usd_c = sum(x["usd"] for x in cand_cases) / len(rows)
    report = {"overrides": overrides, "wins": w, "ties": t, "losses": lo,
              "win_rate_excl_ties": round(w / (w + lo), 3) if w + lo else None,
              "usd_per_ticket": {"active": round(usd_a, 6), "candidate": round(usd_c, 6)}, "diffs": diffs}
    out = ROOT / "evals/results" / ("shadow_" + "_".join(f"{k}-{v}" for k, v in overrides.items()) + ".json")
    out.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "shadow":
        k, v = sys.argv[2].split("=", 1)
        print(json.dumps(shadow({k: int(v) if v.isdigit() else v}), indent=1))
    else:
        print(__doc__)

_ = Path
