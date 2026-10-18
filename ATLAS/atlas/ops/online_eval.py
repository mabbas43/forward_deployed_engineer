"""P7 — online evaluation: sample production runs, judge them asynchronously, alert on drift.

Every hour: 5% random sample + ALL runs rated ≤ 2 (targeted) from the last hour → code checks + validated
judges → `scores`. Then compare the rolling 24 h mean of each key to the previous 24 h; alert if any key drops
≥ 0.03 or the escalation rate doubles. Every alert links to a runbook entry (docs/RUNBOOK.md).

    uv run python -m atlas.ops.online_eval --once
    uv run python -m atlas.ops.online_eval --demo     # seed synthetic runs incl. a regression → see an alert
"""

import argparse
import random
import time

from atlas.logging import get_logger
from atlas.ops.metrics import Metrics, get_metrics

log = get_logger()
SAMPLE_RATE, DROP, WINDOW = 0.05, 0.03, 86400
RUNBOOK = {"grounded": "RB-07 quality drop", "no_pii": "RB-08 PII leak", "escalation_rate": "RB-09 escalation spike"}


def sample(m: Metrics, since: float, rate: float = SAMPLE_RATE, seed: int | None = None) -> list[dict]:
    rows = m.query("SELECT * FROM runs WHERE ts >= ? AND trace_id NOT IN (SELECT trace_id FROM scores "
                   "WHERE source='online')", (since,))
    rnd = random.Random(seed)
    return [r for r in rows if (r["rating"] is not None and r["rating"] <= 2) or rnd.random() < rate]


def judge_run(r: dict) -> dict[str, int]:
    from evals.judges import grounded, no_phantom_ref, no_pii

    inputs, outputs = {"ticket_text": r["ticket_text"]}, {"resolution": r["resolution"], "context_text": r["context_text"]}
    out = {}
    for ev in (grounded, no_phantom_ref, no_pii):
        res = ev(inputs, outputs, {})
        out[res["key"]] = res["score"]
    return out


def window_means(m: Metrics, start: float, end: float) -> dict[str, float]:
    rows = m.query("SELECT key, AVG(score) AS v, COUNT(*) AS n FROM scores WHERE ts>=? AND ts<? GROUP BY key",
                   (start, end))
    out = {r["key"]: r["v"] for r in rows if r["n"] >= 5}
    esc = m.query("SELECT AVG(escalated) AS v, COUNT(*) AS n FROM runs WHERE ts>=? AND ts<?", (start, end))[0]
    if esc["n"] and esc["n"] >= 5:
        out["escalation_rate"] = esc["v"]
    return out


def check_drift(m: Metrics, now: float | None = None) -> list[dict]:
    now = now or time.time()
    cur, prev = window_means(m, now - WINDOW, now), window_means(m, now - 2 * WINDOW, now - WINDOW)
    alerts = []
    for k, v in cur.items():
        if k not in prev:
            continue
        if k == "escalation_rate":
            if prev[k] > 0 and v >= 2 * prev[k]:
                alerts.append({"key": k, "prev": round(prev[k], 3), "cur": round(v, 3)})
        elif prev[k] - v >= DROP:
            alerts.append({"key": k, "prev": round(prev[k], 3), "cur": round(v, 3)})
    for a in alerts:
        a["runbook"] = RUNBOOK.get(a["key"], "RB-07 quality drop")
        m.alert("drift", a["key"], a)
        log.warning("online_eval_alert", **a)
    return alerts


def run_once(m: Metrics | None = None, since_s: int = 3600, seed: int | None = None) -> dict:
    m = m or get_metrics()
    picked = sample(m, time.time() - since_s, seed=seed)
    for r in picked:
        for k, v in judge_run(r).items():
            m.add_score(r["trace_id"], k, v, "online", ts=r["ts"])
    return {"judged": len(picked), "alerts": check_drift(m)}


def seed_demo(m: Metrics) -> None:
    """Two days of synthetic traffic; day 2 has a regression (ungrounded answers + more escalations)."""
    now = time.time()
    good = ("Full-time employees get 30 days of annual leave. [acme/hr/leave-policy.md]",
            "[acme/hr/leave-policy.md] (Annual leave)\nFull-time (40 h): 30 days.")
    bad = ("Full-time employees get 25 days and a bonus week. [acme/hr/leave-policy.md]", good[1])
    for i in range(80):
        day2 = i >= 40
        ts = now - 2 * WINDOW + 600 + i * (2 * WINDOW - 1200) / 80
        res, ctx = (bad if (day2 and i % 3 == 0) else good)
        m.record_run(trace_id=f"demo-{i}", ts=ts, tenant="acme", route="faq", category="hr", latency_ms=900,
                     escalated=int(day2 and i % 2 == 0), blocked=0, usd=0.0004, ticket_text="vacation days?",
                     resolution=res, context_text=ctx, rating=None, versions={}, variant="active")
        for k, v in judge_run({"ticket_text": "vacation days?", "resolution": res, "context_text": ctx}).items():
            m.add_score(f"demo-{i}", k, v, "online", ts=ts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--every", type=int, default=3600)
    a = ap.parse_args()
    if a.demo:
        from atlas.config import settings

        m = Metrics(settings.data_dir / "metrics_demo.sqlite")
        seed_demo(m)
        print({"alerts": check_drift(m)})
        return
    while True:
        print(run_once())
        if a.once:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
