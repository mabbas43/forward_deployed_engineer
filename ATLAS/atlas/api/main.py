"""P8 — the ATLAS API. An agent request is a long-running, expensive, partially-failing JOB, not an HTTP call.

    POST /tickets                    JWT + Idempotency-Key → 202 {ticket_id}       (enqueue, never run inline)
    GET  /tickets/{id}               status + resolution (tenant-scoped)
    GET  /tickets/{id}/events        SSE: node updates → awaiting_approval | resolved
    POST /tickets/{id}/approve       approver decision → queue → ANY worker resumes the thread
    POST /tickets/{id}/feedback      rating (+ corrected plan) → episodic memory + metrics
    POST /ask                        synchronous FAQ path: exact/semantic cache → corrective RAG
    GET  /users/{id}/export          GDPR access   (role: dpo)
    DELETE /users/{id}               GDPR erasure  (role: dpo)

    uv run uvicorn atlas.api.main:app --reload       # in-process workers, local stores
    uv run python scripts/mint_token.py anna.schmidt@acme-logistics.de acme it_support
"""

import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from atlas.agents.feedback import record_feedback
from atlas.agents.ticket_graph import build, config_for, dev_checkpointer
from atlas.api.cache import ExactCache, SemanticCache
from atlas.api.events import EventBus
from atlas.api.queue import InMemoryQueue
from atlas.api.resilience import Dedupe, TokenBucket
from atlas.api.worker import Worker
from atlas.governance.audit import audit, export_user, forget_user, user_hash
from atlas.governance.guards import AI_NOTICE, check_input
from atlas.governance.policy import load_policy
from atlas.mcp.auth import mint_token, verify
from atlas.ops.metrics import get_metrics
from atlas.ops.rollout import variant_for

API_AUD = "atlas-api"
MAX_DEPTH = 1000


@dataclass
class Principal:
    sub: str
    tenant: str
    role: str


class TicketIn(BaseModel):
    text: str = Field(min_length=3, max_length=50_000)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = ""


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    corrected_plan: list[str] | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class Container:
    """Everything stateful the API needs, created once. Tests build one with in-memory parts."""

    def __init__(self, *, checkpointer=None, store=None, workers: int = 2, start_workers: bool = True):
        from atlas.agents.memory import get_store

        self.queue = InMemoryQueue(visibility_timeout=360)
        self.bus = EventBus()
        self.dedupe = Dedupe()
        self.buckets = TokenBucket(rate_per_s=2.0, burst=20)
        self.exact, self.semantic = ExactCache(), SemanticCache()
        self.checkpointer = checkpointer or dev_checkpointer()
        self.store = store if store is not None else get_store()
        self.graph = build(self.checkpointer, self.store)
        self.metrics = get_metrics()
        self.tickets: dict[str, str] = {}  # ticket_id → tenant (ownership for isolation checks)
        self.workers = [Worker(self.queue, self.bus, self.graph, self.metrics, name=f"w{i + 1}") for i in range(workers)]
        if start_workers:
            for w in self.workers:
                w.start()

    def stop(self):
        for w in self.workers:
            w.stop()


def create_app(container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.c = container or Container(workers=int(os.getenv("ATLAS_WORKERS", "2")))
        yield
        app.state.c.stop()

    app = FastAPI(title="ATLAS", version="0.9.0", lifespan=lifespan)

    def c(request: Request) -> Container:
        return request.app.state.c

    def auth(authorization: str = Header(default="")) -> Principal:
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token")
        try:
            claims = verify(authorization.split(" ", 1)[1], aud=API_AUD)
        except Exception as e:
            raise HTTPException(401, f"invalid token: {type(e).__name__}") from e
        return Principal(claims["sub"], claims["tenant"], claims["role"])

    def own(cn: Container, p: Principal, tid: str):
        if cn.tickets.get(tid) != p.tenant:  # another tenant's ticket is indistinguishable from a missing one
            raise HTTPException(404, "ticket not found")

    @app.get("/healthz")
    def healthz(cn: Container = Depends(c)):
        return {"ok": True, "queue_depth": cn.queue.depth(), "breaker": cn.workers[0].breaker.state if cn.workers else None}

    @app.post("/tickets", status_code=202)
    def submit(t: TicketIn, cn: Container = Depends(c), p: Principal = Depends(auth),
               idem: str = Header(alias="Idempotency-Key")):
        key = f"idem:{p.tenant}:{idem}"
        if not cn.dedupe.claim(key):
            existing = cn.dedupe.get(key)
            if existing:
                return {"ticket_id": existing, "deduplicated": True}
            raise HTTPException(409, "duplicate submission in progress")
        if not cn.buckets.take(f"tenant:{p.tenant}"):
            raise HTTPException(429, "tenant rate limit")
        if cn.queue.depth() > MAX_DEPTH:  # backpressure
            raise HTTPException(429, "system busy, retry later")
        if load_policy()["kill_switch"].get("agent"):
            raise HTTPException(503, "ATLAS is paused; please contact the Service Desk")
        tid = f"t-{uuid.uuid4().hex[:10]}"
        cn.tickets[tid] = p.tenant
        cn.dedupe.remember(key, tid)
        cn.queue.send({"kind": "run", "ticket_id": tid, "tenant": p.tenant, "user": p.sub, "role": p.role,
                       "text": t.text, "deadline": time.time() + 300, "variant": variant_for(tid, 0)},
                      group=p.tenant, dedup_id=key)
        audit("ticket_submitted", tenant=p.tenant, user_hash=user_hash(p.sub), role=p.role, trace_id=tid)
        return {"ticket_id": tid}

    @app.get("/tickets/{tid}")
    def get_ticket(tid: str, cn: Container = Depends(c), p: Principal = Depends(auth)):
        own(cn, p, tid)
        st = cn.graph.get_state(config_for(tid))
        v = st.values or {}
        status = "awaiting_approval" if st.next == ("approval",) else ("resolved" if v.get("resolution") and not st.next
                                                                       else "queued" if not v else "running")
        return {"ticket_id": tid, "status": status, "resolution": v.get("resolution"), "plan": v.get("plan"),
                "escalated": v.get("escalated", False), "events": v.get("events", [])}

    @app.get("/tickets/{tid}/events")
    async def events(tid: str, cn: Container = Depends(c), p: Principal = Depends(auth)):
        own(cn, p, tid)

        async def gen():
            async for e in cn.bus.follow(f"events:{p.tenant}:{tid}"):
                yield {"event": e.get("type", "update"), "data": json.dumps(e)}

        return EventSourceResponse(gen())

    @app.post("/tickets/{tid}/approve")
    def approve(tid: str, d: DecisionIn, cn: Container = Depends(c), p: Principal = Depends(auth)):
        own(cn, p, tid)
        if p.role != "it_support":
            raise HTTPException(403, "only it_support may approve actions")
        if cn.graph.get_state(config_for(tid)).next != ("approval",):
            raise HTTPException(409, "ticket is not awaiting approval")
        cn.queue.send({"kind": "resume", "ticket_id": tid, "tenant": p.tenant, "decision":
                       {"decision": d.decision, "approver": user_hash(p.sub)}}, group=p.tenant)
        return {"ok": True}

    @app.post("/tickets/{tid}/feedback")
    def feedback(tid: str, f: FeedbackIn, cn: Container = Depends(c), p: Principal = Depends(auth)):
        own(cn, p, tid)
        v = cn.graph.get_state(config_for(tid)).values
        if not v.get("resolution"):
            raise HTTPException(409, "ticket not resolved yet")
        record_feedback(cn.store, v, f.rating, corrected_plan=f.corrected_plan)
        cn.metrics.rate(v.get("trace_id", tid), f.rating)
        return {"ok": True}

    @app.post("/ask")
    def ask(q: AskIn, cn: Container = Depends(c), p: Principal = Depends(auth)):
        from atlas.rag.crag import ask as crag_ask

        guard = check_input(q.question, load_policy())
        if guard["blocked"]:
            raise HTTPException(400, "request blocked by input guard")
        for layer, cache in (("exact", cn.exact), ("semantic", cn.semantic)):
            hit = cache.get(p.tenant, guard["text"])
            if hit:
                return {**hit, "cache": layer}
        a = crag_ask(guard["text"], p.tenant, p.role)
        out = {"answer": a.answer + AI_NOTICE, "citations": a.citations, "answerable": a.answerable}
        if a.answerable:
            cn.exact.put(p.tenant, guard["text"], out)
            cn.semantic.put(p.tenant, guard["text"], out)
        return {**out, "cache": None}

    @app.get("/users/{user_id}/export")
    def export(user_id: str, cn: Container = Depends(c), p: Principal = Depends(auth)):
        if p.role != "dpo":
            raise HTTPException(403, "dpo only")
        return export_user(user_id, p.tenant, cn.store)

    @app.delete("/users/{user_id}")
    def erase(user_id: str, cn: Container = Depends(c), p: Principal = Depends(auth)):
        if p.role != "dpo":
            raise HTTPException(403, "dpo only")
        return forget_user(user_id, p.tenant, checkpointer=cn.checkpointer, store=cn.store)

    @app.post("/dev/token")
    def dev_token(sub: str, tenant: str, role: str):
        if os.getenv("ATLAS_ENV", "dev") != "dev":
            raise HTTPException(404)
        return {"token": mint_token(sub, tenant, role, aud=API_AUD)}

    return app


app = create_app()
