"""P5 — learning from feedback without fine-tuning: eval failures → candidate prompt → offline gate → registry.

Nothing here deploys. The optimizer writes prompts/<name>.v<N+1>.md; the P7 gate (evals/run.py) scores it on
ALL judges + red team; atlas/ops/registry.py promotes only if no key regresses. An optimizer maximizes the
metric it's given and can regress others — the gate is what makes "self-improving" defensible.

Online with `uv sync --extra optimize`: use DSPy (MIPROv2 / GEPA) with the golden set as trainset and the
P7 judges as the metric. Offline: a transparent rule-based "instruction evolution" from failure categories.
"""

import json
from collections import Counter
from datetime import date
from pathlib import Path

from atlas.config import ROOT
from atlas.llm.prompts import PROMPTS, active_version, header, load

RULES_BY_FAILURE = {
    "right_escalate": "- Escalate (needs_human=true) for HR matters, security incidents and legal topics.",
    "right_category": "- Account lockouts, MFA and VPN problems are `access`; invoices and refunds are `billing`.",
    "grounded": "- Base the reasoning only on facts stated in the ticket.",
    "schema_ok": "- Always return every field; urgency is an integer from 1 to 5.",
}


def failures_from(results_path: Path) -> Counter:
    rows = json.loads(results_path.read_text()).get("rows", [])
    return Counter(k for r in rows for k, v in r.get("scores", {}).items() if v == 0)


def propose_candidate(name: str, failures: Counter, *, use_dspy: bool = False) -> Path:
    if use_dspy:
        raise NotImplementedError("Wire DSPy GEPA/MIPROv2 here: trainset = golden set, metric = P7 judges.")
    current = active_version(name)
    body, _ = load(name, current)
    rules = [RULES_BY_FAILURE[k] for k, _ in failures.most_common() if k in RULES_BY_FAILURE]
    if not rules:
        raise ValueError("no actionable failures — nothing to optimize")
    existing = sorted(int(p.stem.split(".v")[1]) for p in PROMPTS.glob(f"{name}.v*.md"))
    new_v = existing[-1] + 1
    meta = header(name, current)
    path = PROMPTS / f"{name}.v{new_v}.md"
    path.write_text(f"<!-- version: {new_v} | owner: optimizer | created: {date.today()} | parent: v{current} | "
                    f"last-eval: — | score: — | note: candidate from failures {dict(failures)} -->\n"
                    f"{body}\n\nAdditional rules learned from evaluation failures:\n" + "\n".join(rules) + "\n")
    _ = meta
    return path


if __name__ == "__main__":
    import sys

    res = Path(sys.argv[2]) if len(sys.argv) > 2 else max((ROOT / "evals/results").glob("gate_*.json"),
                                                           key=lambda p: p.stat().st_mtime)
    print(propose_candidate(sys.argv[1] if len(sys.argv) > 1 else "triage", failures_from(res)))
