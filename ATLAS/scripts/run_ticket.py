"""Run a ticket through the full graph with PERSISTENT state (SQLite) — approve, kill, resume, rate.

    uv run python scripts/run_ticket.py "I forgot my password" --role it_support
    # it stops at approval and prints the ticket id. Kill the process if you like (that's the drill). Then:
    uv run python scripts/run_ticket.py --resume t-1234abcd --decision approve
    uv run python scripts/run_ticket.py --feedback t-1234abcd --rating 5
"""

import argparse
import json

from langgraph.types import Command

from atlas.agents.feedback import record_feedback
from atlas.agents.memory import get_store
from atlas.agents.ticket_graph import build, config_for, dev_checkpointer, new_ticket
from atlas.llm.budget import BudgetTracker

ap = argparse.ArgumentParser()
ap.add_argument("ticket", nargs="?")
ap.add_argument("--role", default="it_support")
ap.add_argument("--user", default="anna.schmidt@acme-logistics.de")
ap.add_argument("--tenant", default="acme")
ap.add_argument("--resume")
ap.add_argument("--decision", default="approve", choices=["approve", "reject"])
ap.add_argument("--feedback")
ap.add_argument("--rating", type=int, default=5)
a = ap.parse_args()

store = get_store()
g = build(dev_checkpointer(), store)
if a.feedback:
    v = g.get_state(config_for(a.feedback)).values
    print(record_feedback(store, v, a.rating).model_dump())
    raise SystemExit
tracker = BudgetTracker(0.25)
if a.resume:
    cfg = config_for(a.resume, callbacks=[tracker])
    out = g.invoke(Command(resume={"decision": a.decision, "approver": "cli"}), cfg)
    tid = a.resume
else:
    t = new_ticket(a.ticket, tenant=a.tenant, user_id=a.user, role=a.role)
    tid = t["ticket_id"]
    cfg = config_for(tid, callbacks=[tracker])
    out = g.invoke(t, cfg)
st = g.get_state(config_for(tid))
print(json.dumps({"ticket_id": tid, "events": out.get("events"), "plan": out.get("plan"),
                  "next": st.next, "usd": round(tracker.total_usd, 6)}, indent=2))
if st.next == ("approval",):
    print(f"\n⏸  awaiting approval. Resume with:\n   uv run python scripts/run_ticket.py --resume {tid} --decision approve")
else:
    print("\n" + out.get("resolution", ""))
