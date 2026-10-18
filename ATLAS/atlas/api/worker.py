"""P8 — the stateless worker. Holds nothing between steps: the checkpointer and store hold everything, so ANY
worker can run or resume ANY ticket (thread_id = ticket_id). That one decision buys horizontal scaling, crash
recovery, zero-drain deploys and approvals that wait for days.

    uv run python -m atlas.api.worker      # standalone (needs a shared queue: SQS via QUEUE_URL)
"""

import threading
import time

from langgraph.types import Command

from atlas.agents.ticket_graph import config_for, new_ticket
from atlas.api.resilience import CircuitBreaker, CircuitOpen
from atlas.governance.guards import AI_NOTICE
from atlas.governance.policy import load_policy
from atlas.llm.budget import BudgetExceeded, BudgetTracker
from atlas.llm.prompts import active
from atlas.logging import get_logger
from atlas.ops.telemetry import OTelGenAICallback
from atlas.rag.generate import format_context

log = get_logger()


class Worker:
    def __init__(self, queue, bus, graph, metrics=None, breaker: CircuitBreaker | None = None, name: str = "w1"):
        self.queue, self.bus, self.graph, self.metrics, self.name = queue, bus, graph, metrics, name
        self.breaker = breaker or CircuitBreaker("llm", fail_threshold=5, reset_after=60)
        self._stop = threading.Event()

    def stream(self, body: dict) -> str:
        return f"events:{body['tenant']}:{body['ticket_id']}"

    def handle(self, msg) -> None:
        body, s = msg.body, self.stream(msg.body)
        tid = body["ticket_id"]
        if body.get("deadline") and time.time() > body["deadline"]:
            self.bus.publish(s, {"type": "failed", "reason": "deadline_exceeded"})
            self.queue.ack(msg)
            return
        try:
            self.breaker.before()
        except CircuitOpen:
            self.bus.publish(s, {"type": "failed", "reason": "providers_unavailable",
                                 "message": "AI providers are unavailable; your ticket is queued for a colleague."})
            self.queue.ack(msg)
            return
        tracker = BudgetTracker(load_policy()["limits"]["usd_per_request"], tags=[f"tenant:{body['tenant']}"])
        cfg = config_for(tid, callbacks=[tracker, OTelGenAICallback()], tags=[f"tenant:{body['tenant']}", self.name],
                         metadata={"tenant": body["tenant"], "ticket_id": tid})
        inp = Command(resume=body["decision"]) if body["kind"] == "resume" else new_ticket(
            body["text"], tenant=body["tenant"], user_id=body["user"], role=body["role"], ticket_id=tid)
        t0 = time.perf_counter()
        try:
            for ev in self.graph.stream(inp, cfg, stream_mode="updates"):
                for node in ev:
                    self.bus.publish(s, {"type": "update", "node": node, "worker": self.name})
                self.queue.extend(msg, 360)  # keep the message invisible while we're alive and working
            self.breaker.on_success()
        except BudgetExceeded as e:
            self.bus.publish(s, {"type": "failed", "reason": "budget", "detail": str(e)})
            self.queue.ack(msg)
            return
        except Exception as e:  # don't ack: visibility timeout → redelivery → resume from last checkpoint
            self.breaker.on_failure()
            log.error("worker_error", ticket_id=tid, err=repr(e))
            self.bus.publish(s, {"type": "retrying", "reason": type(e).__name__})
            return
        st = self.graph.get_state(cfg)
        if st.next == ("approval",):
            intr = st.tasks[0].interrupts[0].value if st.tasks and st.tasks[0].interrupts else {}
            self.bus.publish(s, {"type": "awaiting_approval", "plan": intr.get("plan"), "writes": intr.get("writes")})
        else:
            v = st.values
            self.bus.publish(s, {"type": "resolved", "resolution": v.get("resolution"),
                                 "escalated": v.get("escalated", False)})
            if self.metrics:
                self.metrics.record_run(
                    trace_id=v.get("trace_id", tid), tenant=body["tenant"], route=(v.get("route") or {}).get("name"),
                    category=(v.get("triage") or {}).get("category"), escalated=int(bool(v.get("escalated"))),
                    blocked=int(bool(v.get("blocked"))), latency_ms=int((time.perf_counter() - t0) * 1000),
                    usd=tracker.total_usd, ticket_text=v.get("ticket_text"),
                    resolution=(v.get("resolution") or "").replace(AI_NOTICE, ""),
                    context_text=format_context(v.get("context", [])), versions=active().get("prompts", {}),
                    variant=body.get("variant", "active"))
        self.queue.ack(msg)

    def run_forever(self, poll: float = 0.05) -> None:
        while not self._stop.is_set():
            msg = self.queue.receive()
            if msg is None:
                time.sleep(poll)
                continue
            self.handle(msg)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, daemon=True, name=f"worker-{self.name}")
        t.start()
        return t

    def stop(self):
        self._stop.set()


if __name__ == "__main__":
    import os

    from atlas.agents.memory import get_store
    from atlas.agents.ticket_graph import build, dev_checkpointer
    from atlas.api.events import EventBus
    from atlas.api.queue import SQSQueue
    from atlas.ops.metrics import get_metrics

    url = os.environ.get("QUEUE_URL")
    if not url:
        raise SystemExit("standalone worker needs QUEUE_URL (SQS). For local dev, the API runs in-process workers.")
    Worker(SQSQueue(url), EventBus(), build(dev_checkpointer(), get_store()), get_metrics()).run_forever()
