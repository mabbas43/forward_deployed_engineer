"""P1 checkpoint task: triage CLI with --budget, --version, --batch, --repeat.

    uv run python scripts/triage.py "VPN drops every 10 min"
    uv run python scripts/triage.py "reset my password" --budget 0.00001      # refused cleanly (drill 5)
    uv run python scripts/triage.py "printer is weird again" --repeat 20       # non-determinism baseline (M1.7)
    uv run python scripts/triage.py --batch data/tickets/stream_v1.jsonl --version 2
"""

import argparse
import json
from collections import Counter

from atlas.llm.budget import BudgetExceeded, BudgetTracker
from atlas.llm.client import triage, triage_chain
from atlas.llm.prompts import load
from atlas.llm.tokens import InputTooLarge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticket", nargs="?")
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--version", type=int, default=None)
    ap.add_argument("--batch", help="jsonl with a ticket_text field per line")
    ap.add_argument("--repeat", type=int, default=0, help="run the same ticket N times via .batch()")
    a = ap.parse_args()
    try:
        if a.repeat:
            system, v = load("triage", a.version)
            tracker = BudgetTracker(a.budget or 1.0, tags=[f"prompt:triage.v{v}", "experiment:repeat"])
            msgs = [[("system", system), ("human", f"<ticket>\n{a.ticket}\n</ticket>")]] * a.repeat
            outs = triage_chain.batch(msgs, config={"callbacks": [tracker], "max_concurrency": 5})
            cats = Counter(o.category for o in outs)
            print(json.dumps({"runs": a.repeat, "distinct_reasonings": len({o.reasoning for o in outs}),
                              "categories": dict(cats), "category_flips": len(cats) - 1,
                              "urgencies": dict(Counter(o.urgency for o in outs)), "usd": round(tracker.total_usd, 6)},
                             indent=2))
        elif a.batch:
            rows = [json.loads(x) for x in open(a.batch) if x.strip()]
            for r in rows:
                t = triage(r["ticket_text"], budget_usd=a.budget, prompt_version=a.version)
                print(json.dumps({"ticket": r["ticket_text"][:60], **t.model_dump()}))
        else:
            print(json.dumps(triage(a.ticket, budget_usd=a.budget, prompt_version=a.version).model_dump(), indent=2))
    except BudgetExceeded as e:
        raise SystemExit(f"refused: {e}") from None
    except InputTooLarge as e:
        raise SystemExit(f"refused by token gate: {e}") from None


if __name__ == "__main__":
    main()
