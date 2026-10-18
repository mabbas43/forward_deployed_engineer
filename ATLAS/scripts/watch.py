"""P3 M3.6: stream a ticket node by node (`updates`), the way an ops dashboard would see it.

    uv run python scripts/watch.py "My account is locked, please unlock"
"""

import sys

from langgraph.checkpoint.memory import InMemorySaver

from atlas.agents.memory import memory_store
from atlas.agents.ticket_graph import build, config_for, new_ticket

t = new_ticket(" ".join(sys.argv[1:]) or "My account is locked, please unlock")
g = build(InMemorySaver(), memory_store())
for update in g.stream(t, config_for(t["ticket_id"]), stream_mode="updates"):
    for node, delta in update.items():
        keys = ", ".join(k for k in (delta or {}) if k not in {"events", "messages"})
        print(f"▶ {node:<16} {keys}")
print("next:", g.get_state(config_for(t["ticket_id"])).next or "done")
