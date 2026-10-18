"""Phase 3 — durable, resumable state machines with approval gates and idempotent tools."""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from atlas.agents.steps import has_writes, parse_step
from atlas.agents.ticket_graph import config_for, new_ticket
from atlas.mcp import backends


def test_step_parser():
    assert parse_step('CALL: reset_password(email=a@b.de, note="x, y")') == (
        "CALL", "reset_password", {"email": "a@b.de", "note": "x, y"})
    assert parse_step("ANSWER: hello")[0] == "ANSWER"
    assert parse_step("do something")[0] == "INVALID"
    assert has_writes(["READ: lookup_user(email=a)", "CALL: unlock_account(email=a)"])


def test_write_plan_interrupts_for_approval_and_resumes(run_ticket):
    out, g, cfg = run_ticket("I forgot my password and need a reset")
    assert g.get_state(cfg).next == ("approval",)
    assert any(p.startswith("CALL: reset_password") for p in out["plan"])
    out = g.invoke(Command(resume="approve"), cfg)
    assert g.get_state(cfg).next == ()
    assert "reset" in out["resolution"].lower()


def test_rejection_changes_nothing(run_ticket):
    before = len(backends.ledger.side_effects)
    out, g, cfg = run_ticket("My account is locked, please unlock", approve=False)
    assert out["approved"] is False
    assert len(backends.ledger.side_effects) == before
    assert "not approved" in out["resolution"]


def test_read_only_ticket_never_interrupts(run_ticket):
    out, g, cfg = run_ticket("How many vacation days do I get per year?", role="employee")
    assert g.get_state(cfg).next == ()
    assert "30" in out["resolution"]


def test_hr_routes_to_escalation_not_action(run_ticket):
    out, _, _ = run_ticket("My salary payment is missing this month", role="employee",
                           user="clara.wagner@acme-logistics.de")
    assert out["escalated"] is True and "escalate" in out["events"]
    assert not out.get("tool_results")


def test_approval_survives_process_restart(tmp_path, graph_factory):
    db = tmp_path / "cp.sqlite"
    t = new_ticket("I forgot my password and need a reset", ticket_id="t-restart")
    cfg = config_for("t-restart")
    g1 = graph_factory(SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    g1.invoke(t, cfg)
    assert g1.get_state(cfg).next == ("approval",)
    del g1  # "kill the process"
    g2 = graph_factory(SqliteSaver(sqlite3.connect(db, check_same_thread=False)))  # "restart"
    assert g2.get_state(cfg).next == ("approval",)
    out = g2.invoke(Command(resume="approve"), cfg)
    assert "reset" in out["resolution"].lower()


def test_resume_never_repeats_a_side_effect(run_ticket, graph_factory):
    """Idempotency keys are (ticket_id, step): executing the same approved plan twice sends one reset."""
    g = graph_factory()
    out, g, cfg = run_ticket("I forgot my password and need a reset", graph=g, approve=True, ticket_id="t-idem")
    n = sum(1 for e in backends.ledger.side_effects if e["key"].endswith("t-idem:1"))
    hist = [s for s in g.get_state_history(cfg) if s.next == ("execute",)]
    g.invoke(None, hist[0].config)  # replay execute from its checkpoint (what a crash-resume does)
    assert sum(1 for e in backends.ledger.side_effects if e["key"].endswith("t-idem:1")) == n == 1


def test_trajectory_events_recorded(run_ticket):
    out, _, _ = run_ticket("Supplier invoice INV-88231 was paid twice", approve=True)
    seq = out["events"]
    assert seq.index("retrieve") < seq.index("plan") < seq.index("approval") < seq.index("execute")


def test_time_travel_fork_with_edited_plan(run_ticket):
    out, g, cfg = run_ticket("I forgot my password and need a reset")
    at_approval = g.get_state(cfg)
    fork = g.update_state(at_approval.config, {"plan": ["READ: lookup_user(email=anna.schmidt@acme-logistics.de)"]},
                          as_node="reflect")
    out = g.invoke(None, fork)
    assert all(not p.startswith("CALL") for p in out["plan"])


def test_thread_id_is_ticket_id():
    assert config_for("t-1")["configurable"]["thread_id"] == "t-1"


def test_request_budget_sees_every_llm_call_in_the_graph(graph_factory):
    """Regression: an explicit `callbacks=[]` in a child call once hid plan/respond calls from the budget."""
    from atlas.llm.budget import BudgetTracker

    g = graph_factory()
    t = new_ticket("I forgot my password and need a reset")
    tracker = BudgetTracker(1.0)
    g.invoke(t, config_for(t["ticket_id"], callbacks=[tracker]))
    assert tracker.calls >= 3  # triage + plan + critique at least (before the approval pause)
