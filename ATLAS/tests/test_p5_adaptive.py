"""Phase 5 — memory with namespace isolation, bounded reflection, data-driven routing, tool RAG, supervisor."""

import json
from pathlib import Path

from atlas.agents import memory as mem
from atlas.agents.memory import Case, memory_store
from atlas.agents.router import route


def case(ticket, rating, plan=("ANSWER: x",)):
    return Case(ticket=ticket, plan=list(plan), outcome="o", rating=rating)


def test_namespaces_isolate_tenants_and_users():
    s = memory_store()
    mem.remember_case(s, "acme", "t1", case("password reset for warehouse scanner", 5))
    assert mem.recall_cases(s, "globex", "password reset", k=3) == ([], [])
    mem.put_prefs(s, "acme", "userA", {"language": "de"}, "tr1")
    assert mem.prefs(s, "acme", "userB") == {}
    assert mem.prefs(s, "acme", "userA") == {"language": "de"}


def test_low_rated_cases_are_never_positive_examples():
    s = memory_store()
    mem.remember_case(s, "acme", "good", case("vpn drops every few minutes", 5))
    mem.remember_case(s, "acme", "bad", case("vpn drops every few minutes again", 1))
    good, avoid = mem.recall_cases(s, "acme", "vpn keeps dropping")
    assert all(c["rating"] >= 4 for c in good) and all(c["rating"] <= 2 for c in avoid) and avoid


def test_forget_user_memory():
    s = memory_store()
    mem.put_prefs(s, "acme", "u1", {"language": "de"}, "tr")
    assert mem.forget_user_memory(s, "acme", "u1") == 1
    assert mem.prefs(s, "acme", "u1") == {}


def test_reflection_is_bounded(graph_factory, monkeypatch, run_ticket):
    from atlas.agents import ticket_graph
    from atlas.agents.reflect import MAX_ITER, Critique

    monkeypatch.setattr(ticket_graph, "critique", lambda s, tools: Critique(passes=False, issues=["never good"],
                                                                             must_fix=True))
    out, _, _ = run_ticket("My account is locked, please unlock")
    assert out["iterations"] == MAX_ITER  # the loop stopped; it did not bill forever
    assert out["events"].count("reflect") == MAX_ITER


def test_router_accuracy_on_labelled_requests():
    labelled = [("How do I set up VPN at home?", "faq"), ("What is the password policy?", "faq"),
                ("How many vacation days do I have?", "faq"), ("Where do I submit expenses?", "faq"),
                ("I'm locked out, please reset my password", "ticket"), ("Outlook crashes when I open files", "ticket"),
                ("We were charged twice for an invoice", "ticket"), ("Please give me access to the HR drive", "ticket"),
                ("I want to complain about my team lead", "escalate"), ("I clicked a phishing link", "escalate"),
                ("Possible data breach: customer data sent outside", "escalate"),
                ("A colleague is harassing me at work", "escalate")]
    correct = sum(route(t)["name"] == r for t, r in labelled)
    assert correct / len(labelled) >= 0.75


def test_tool_selection_returns_relevant_subset():
    from atlas.agents.tool_select import select
    from atlas.agents.tools import TOOLS

    picked = [t.name for t in select("supplier invoice was paid twice", TOOLS, k=3)]
    assert "lookup_invoice" in picked or "request_credit_note" in picked


def test_supervisor_hands_off_with_compact_brief():
    from atlas.agents.supervisor import build

    out = build().invoke({"ticket_text": "My MFA stopped working, reset it", "user_email": "a@acme-logistics.de",
                          "tenant": "acme", "triage": {"category": "access"}})
    assert out["specialist"] == "access" and len(out["brief"]) < 200
    assert any("reset_mfa" in p for p in out["plan"])


def test_episodic_memory_fixes_unknown_phrasing(graph_factory, run_ticket):
    """The P5 mechanism in one test: a human-corrected case teaches the planner a phrasing its rules miss."""
    from atlas.agents.feedback import record_feedback

    store = memory_store()
    g = graph_factory(store=store, routing=False, grounding=False)
    text = "can't get into my email, the passphrase isn't accepted anymore"
    out, _, _ = run_ticket(text, graph=g)
    assert not any(p.startswith("CALL") for p in out["plan"])  # rules alone: no idea
    record_feedback(store, out, 1, corrected_plan=["READ: lookup_user(email=anna.schmidt@acme-logistics.de)",
                                                   "CALL: reset_password(email=anna.schmidt@acme-logistics.de)"],
                    run_extractor=False)
    out2, _, _ = run_ticket("passphrase not accepted for my email, please send a new one", graph=g)
    assert any("reset_password" in p for p in out2["plan"])


def test_extractor_never_stores_pii():
    from atlas.agents.extract import extract_and_store

    s = memory_store()
    x = extract_and_store(s, "Bitte call me at +49 170 1234567 about my MFA verification", "acme", "u1", "tr1")
    assert x.contains_pii and mem.prefs(s, "acme", "u1") == {}


def test_optimizer_writes_candidate_without_deploying(tmp_path, monkeypatch):
    from collections import Counter

    from atlas.agents import optimize
    from atlas.llm import prompts

    for f in Path(prompts.PROMPTS).glob("*"):
        (tmp_path / f.name).write_text(f.read_text())
    monkeypatch.setattr(optimize, "PROMPTS", tmp_path)
    monkeypatch.setattr(prompts, "PROMPTS", tmp_path)
    before = (tmp_path / "active.yaml").read_text()
    path = optimize.propose_candidate("triage", Counter({"right_escalate": 3}))
    assert path.name == "triage.v3.md" and "Escalate" in path.read_text()
    assert (tmp_path / "active.yaml").read_text() == before  # nothing promoted
    _ = json
