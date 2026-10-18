"""P5 — the experiment that goes in your portfolio: does ATLAS get better with use?

Replays 60 tickets in arrival order, twice: memory ON vs memory OFF. After each ticket a simulated reviewer
judges the plan against the expected tools. Pass → stored as a well-rated case. Fail → a human resolves it and
the *corrected* plan is stored as a high-rated case (that's how real support teams teach the system).
Memory-on should climb; memory-off should stay flat.

    uv run python -m evals.adaptive_curve           # writes evals/results/adaptive_curve.{json,png|txt}

Offline, the planner is rule-based and only memory can fix phrasings its rules miss — so the curve shows the
*mechanism*. Run with real models for the number you publish.
"""

import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from atlas.agents.feedback import record_feedback
from atlas.agents.memory import memory_store
from atlas.agents.steps import parse_step
from atlas.agents.ticket_graph import GraphOptions, build, config_for, new_ticket

ROOT = Path(__file__).resolve().parents[1]
STREAM = ROOT / "data/tickets/stream_v1.jsonl"
OUT = ROOT / "evals/results"
WINDOW = 10


def passes(plan: list[str], expected_tools: list[str]) -> bool:
    writes = [t for k, t, _ in map(parse_step, plan) if k == "CALL"]
    return sorted(writes) == sorted(t for t in expected_tools if t not in {"lookup_user", "lookup_invoice"})


def replay(memory_on: bool) -> list[int]:
    store = memory_store()
    g = build(InMemorySaver(), store, GraphOptions(memory=memory_on, routing=False, grounding=False))
    results = []
    for row in (json.loads(x) for x in STREAM.read_text().splitlines() if x.strip()):
        t = new_ticket(row["ticket_text"], tenant=row["tenant"], user_id=row["user_id"], role=row["user_role"],
                       ticket_id=f"{row['id']}-{'on' if memory_on else 'off'}")
        cfg = config_for(t["ticket_id"])
        out = g.invoke(t, cfg)
        if g.get_state(cfg).next == ("approval",):
            out = g.invoke(Command(resume="approve"), cfg)
        ok = passes(out.get("plan", []), row["expected_tools"])
        results.append(int(ok))
        if memory_on:
            record_feedback(store, out, rating=5 if ok else 1,
                            corrected_plan=None if ok else row["expected_plan"] or None, run_extractor=False)
    return results


def rolling(xs: list[int], w: int = WINDOW) -> list[float]:
    return [round(sum(xs[max(0, i - w + 1) : i + 1]) / len(xs[max(0, i - w + 1) : i + 1]), 3) for i in range(len(xs))]


def main():
    on, off = replay(True), replay(False)
    res = {"memory_on": on, "memory_off": off, "rolling_on": rolling(on), "rolling_off": rolling(off),
           "first20_on": sum(on[:20]) / 20, "last20_on": sum(on[-20:]) / 20,
           "first20_off": sum(off[:20]) / 20, "last20_off": sum(off[-20:]) / 20}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "adaptive_curve.json").write_text(json.dumps(res, indent=1))
    print(f"pass rate  first 20 → last 20\n  memory ON : {res['first20_on']:.2f} → {res['last20_on']:.2f}\n"
          f"  memory OFF: {res['first20_off']:.2f} → {res['last20_off']:.2f}")
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(res["rolling_on"], label="memory on")
        ax.plot(res["rolling_off"], label="memory off", linestyle="--")
        ax.set(xlabel="ticket #", ylabel=f"rolling pass rate (window {WINDOW})", ylim=(0, 1.05),
               title="ATLAS adaptive curve")
        ax.legend()
        fig.tight_layout()
        fig.savefig(OUT / "adaptive_curve.png", dpi=120)
        print(f"plot → {OUT / 'adaptive_curve.png'}")
    except ImportError:
        lines = [f"{i + 1:>3} on {'#' * int(a * 40):<40} off {'#' * int(b * 40)}"
                 for i, (a, b) in enumerate(zip(res["rolling_on"], res["rolling_off"], strict=True)) if i % 5 == 4]
        (OUT / "adaptive_curve.txt").write_text("\n".join(lines) + "\n")
        print("\n".join(lines))


if __name__ == "__main__":
    main()
