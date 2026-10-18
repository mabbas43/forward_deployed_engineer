"""Phase 8 — API + queue + stateless workers: idempotency, isolation, fairness, breakers, caches."""

import time

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from atlas.agents.memory import memory_store
from atlas.api.main import API_AUD, Container, create_app
from atlas.api.queue import InMemoryQueue
from atlas.api.resilience import CircuitBreaker, CircuitOpen, Dedupe, TokenBucket
from atlas.mcp.auth import mint_token


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def H(sub="anna.schmidt@acme-logistics.de", role="it_support", tenant="acme", idem=None):
    h = {"Authorization": "Bearer " + mint_token(sub, tenant, role, aud=API_AUD)}
    return {**h, "Idempotency-Key": idem} if idem else h


@pytest.fixture
def api():
    cont = Container(checkpointer=InMemorySaver(), store=memory_store(), workers=2)
    with TestClient(create_app(cont)) as c:
        yield c, cont


def wait(c, tid, h, states=("awaiting_approval", "resolved"), timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get(f"/tickets/{tid}", headers=h).json()
        if st["status"] in states:
            return st
        time.sleep(0.05)
    raise AssertionError(f"timeout; last={st}")


def test_auth_and_idempotency(api):
    c, _ = api
    assert c.post("/tickets", json={"text": "hello there"}, headers={"Idempotency-Key": "a"}).status_code == 401
    r1 = c.post("/tickets", json={"text": "VPN drops every ten minutes"}, headers=H(idem="same")).json()
    r2 = c.post("/tickets", json={"text": "VPN drops every ten minutes"}, headers=H(idem="same")).json()
    assert r1["ticket_id"] == r2["ticket_id"] and r2["deduplicated"]


def test_full_approval_flow_and_tenant_isolation(api):
    c, cont = api
    h = H(idem="flow-1")
    tid = c.post("/tickets", json={"text": "I forgot my password, please reset it"}, headers=h).json()["ticket_id"]
    assert wait(c, tid, h)["status"] == "awaiting_approval"
    assert c.get(f"/tickets/{tid}", headers=H("sam.lee@globex.example", tenant="globex")).status_code == 404
    assert c.post(f"/tickets/{tid}/approve", json={"decision": "approve"}, headers=H(role="employee")).status_code == 403
    assert c.post(f"/tickets/{tid}/approve", json={"decision": "approve"}, headers=h).status_code == 200
    st = wait(c, tid, h, ("resolved",))
    assert "reset" in st["resolution"].lower()
    types = [e["type"] for e in cont.bus.read(f"events:acme:{tid}")]
    assert "awaiting_approval" in types and types[-1] == "resolved"
    assert c.post(f"/tickets/{tid}/feedback", json={"rating": 5}, headers=h).json() == {"ok": True}


def test_ask_uses_versioned_cache(api):
    c, _ = api
    a = c.post("/ask", json={"question": "What does error E-4471 mean?"}, headers=H()).json()
    b = c.post("/ask", json={"question": "What does error E-4471 mean?"}, headers=H()).json()
    assert a["cache"] is None and b["cache"] == "exact"


def test_gdpr_endpoints_are_dpo_only(api):
    c, _ = api
    assert c.delete("/users/x@acme-logistics.de", headers=H()).status_code == 403
    assert c.delete("/users/x@acme-logistics.de", headers=H("dpo@acme-logistics.de", "dpo")).status_code == 200


def test_circuit_breaker_opens_and_half_opens():
    clk = Clock()
    b = CircuitBreaker("p", fail_threshold=2, reset_after=10, clock=clk)

    def boom():
        raise RuntimeError("429")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            b.call(boom)
    assert b.state == "open"
    with pytest.raises(CircuitOpen):
        b.call(lambda: 1)
    clk.t = 11
    assert b.state == "half_open" and b.call(lambda: 1) == 1 and b.state == "closed"


def test_token_bucket_refills():
    clk = Clock()
    tb = TokenBucket(rate_per_s=1, burst=2, clock=clk)
    assert tb.take("a") and tb.take("a") and not tb.take("a")
    assert tb.take("b")  # per-key buckets
    clk.t = 1.1
    assert tb.take("a")


def test_dedupe_ttl():
    clk = Clock()
    d = Dedupe(clock=clk)
    assert d.claim("k", ttl=5) and not d.claim("k", ttl=5)
    clk.t = 6
    assert d.claim("k", ttl=5)


def test_queue_fairness_round_robin():
    q = InMemoryQueue()
    for i in range(50):
        q.send({"i": i}, group="tenant-a")
    q.send({"i": "b"}, group="tenant-b")
    first_two = [q.receive().group for _ in range(2)]
    assert "tenant-b" in first_two  # B is not stuck behind A's backlog


def test_visibility_timeout_redelivery_and_dlq():
    clk = Clock()
    q = InMemoryQueue(visibility_timeout=30, max_receives=2, clock=clk)
    q.send({"x": 1}, group="t")
    m = q.receive()
    assert q.receive() is None  # invisible while in flight
    clk.t = 31
    assert q.receive().id == m.id  # crashed worker → redelivered
    clk.t = 62
    assert q.receive() is None and len(q.dlq) == 1


def test_queue_dedup_id():
    q = InMemoryQueue()
    assert q.send({"a": 1}, "t", dedup_id="x") and q.send({"a": 1}, "t", dedup_id="x") is None


def test_cache_key_includes_prompt_and_retrieval_version(monkeypatch):
    from atlas.api import cache
    from atlas.llm import prompts

    k1 = cache.version_key("acme")
    orig = prompts.active
    monkeypatch.setattr(prompts, "active", lambda: {**orig(), "prompts": {**orig()["prompts"], "answer": 9}})
    assert cache.version_key("acme") != k1
