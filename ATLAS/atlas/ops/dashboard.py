"""P7 — one dashboard, per route, per day: quality pass rates, p95 latency, $/ticket, block rate, escalation rate.

    uv run python -m atlas.ops.dashboard              # terminal table
    uv sync --extra dashboard && uv run streamlit run atlas/ops/dashboard.py
"""

import statistics
import time
from collections import defaultdict

from atlas.ops.metrics import Metrics, get_metrics


def report(m: Metrics | None = None, days: int = 7) -> list[dict]:
    m = m or get_metrics()
    since = time.time() - days * 86400
    runs = m.query("SELECT * FROM runs WHERE ts >= ?", (since,))
    scores = m.query("SELECT s.key, s.score, r.route, r.ts FROM scores s JOIN runs r USING(trace_id) WHERE r.ts >= ?",
                     (since,))
    by = defaultdict(list)
    for r in runs:
        by[(time.strftime("%Y-%m-%d", time.localtime(r["ts"])), r["route"] or "?")].append(r)
    qual = defaultdict(list)
    for s in scores:
        qual[(time.strftime("%Y-%m-%d", time.localtime(s["ts"])), s["route"] or "?", s["key"])].append(s["score"])
    out = []
    for (day, route), rs in sorted(by.items()):
        lat = sorted(r["latency_ms"] or 0 for r in rs)
        row = {"day": day, "route": route, "tickets": len(rs),
               "p95_ms": lat[int(0.95 * (len(lat) - 1))] if lat else 0,
               "usd_per_ticket": round(statistics.mean(r["usd"] or 0 for r in rs), 5),
               "block_rate": round(statistics.mean(r["blocked"] or 0 for r in rs), 3),
               "escalation_rate": round(statistics.mean(r["escalated"] or 0 for r in rs), 3)}
        for key in ("grounded", "no_phantom_ref", "no_pii"):
            v = qual.get((day, route, key))
            row[key] = round(statistics.mean(v), 3) if v else None
        out.append(row)
    return out


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("no runs yet — serve some tickets (scripts/run_ticket.py or the API) first")
        return
    cols = list(rows[0])
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(r[c]) for c in cols))


def streamlit_app():
    import streamlit as st

    st.set_page_config(page_title="ATLAS ops", layout="wide")
    st.title("ATLAS — quality, latency, cost per route")
    rows = report()
    st.dataframe(rows, use_container_width=True)
    alerts = get_metrics().query("SELECT * FROM alerts ORDER BY ts DESC LIMIT 20")
    st.subheader("Alerts")
    st.dataframe(alerts, use_container_width=True)


if __name__ == "__main__":
    try:
        import streamlit.runtime

        if streamlit.runtime.exists():
            streamlit_app()
        else:
            print_table(report())
    except ImportError:
        print_table(report())
