"""Phase 1 — typed, cost-tracked, budget-limited, fallback-protected LLM client. No network."""

import pytest
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from atlas.llm.budget import BudgetExceeded, BudgetTracker
from atlas.llm.cost import CostTracker, usd
from atlas.llm.offline import OfflineChatModel
from atlas.llm.prompts import header, load
from atlas.llm.schemas import TicketTriage
from atlas.llm.tokens import InputTooLarge, assert_fits


def test_schema_rejects_bad_category():
    with pytest.raises(ValidationError):
        TicketTriage(reasoning="x", category="spam", urgency=3, needs_human=False)


def test_schema_rejects_out_of_range_urgency():
    with pytest.raises(ValidationError):
        TicketTriage(reasoning="x", category="bug", urgency=9, needs_human=False)


def test_reasoning_is_first_field():
    assert list(TicketTriage.model_fields)[0] == "reasoning"


def test_token_gate_blocks_large_input():
    with pytest.raises(InputTooLarge):
        assert_fits("sys", "word " * 20_000, "gpt-4.1-mini")


def test_usd_math_and_dated_model_names():
    assert usd("gpt-4.1-mini", 1_000_000, 0) == pytest.approx(0.40)
    assert usd("gpt-4.1-mini-2025-04-14", 0, 1_000_000) == pytest.approx(1.60)
    assert usd("gpt-4.1-mini", 1_000_000, 0, cached_in=1_000_000) == pytest.approx(0.10)


def test_prompt_loader_strips_header_and_parses_it():
    body, v = load("triage", 1)
    assert v == 1 and not body.startswith("<!--")
    assert header("triage", 1)["version"] == "1"


def test_cost_tracker_logs_every_call():
    t = CostTracker()
    OfflineChatModel().with_structured_output(TicketTriage).invoke(
        [("system", "x"), ("human", "<ticket>\nVPN drops\n</ticket>")], config={"callbacks": [t]})
    assert t.calls == 1 and t.total_usd > 0 and t.models == ["offline-heuristic"]


def test_budget_refuses_before_spending():
    t = BudgetTracker(budget_usd=0.0000001)
    with pytest.raises(BudgetExceeded):
        OfflineChatModel().with_structured_output(TicketTriage).invoke(
            [("human", "<ticket>\nreset my password\n</ticket>")], config={"callbacks": [t]})
    assert t.calls == 0  # refused pre-call: nothing was spent


def test_triage_with_budget_raises():
    from atlas.llm.client import triage

    with pytest.raises(BudgetExceeded):
        triage("reset my password", budget_usd=0.0000001)


def test_token_gate_rejects_before_model_is_called(monkeypatch):
    from atlas.llm import client

    called = []
    monkeypatch.setattr(client, "triage_chain", RunnableLambda(lambda x: called.append(x)))
    with pytest.raises(InputTooLarge):
        client.triage("log line " * 30_000)
    assert not called


def test_fallback_fires_when_primary_raises(monkeypatch):
    from atlas.llm import client

    def primary(_):
        raise RuntimeError("openai down")

    backup_calls = []

    def backup(_):
        backup_calls.append(1)
        return TicketTriage(reasoning="r", category="access", urgency=3, needs_human=False)

    monkeypatch.setattr(client, "triage_chain", RunnableLambda(primary).with_fallbacks([RunnableLambda(backup)]))
    assert client.triage("VPN drops", budget_usd=1.0).category == "access"
    assert backup_calls == [1]


@pytest.mark.parametrize("text,cat", [("Cannot log in to SSO since this morning", "access"),
                                      ("Invoice was charged twice", "billing"),
                                      ("Outlook crashes with an error", "bug"),
                                      ("I need to change my vacation dates", "hr")])
def test_offline_triage_categories(text, cat):
    from atlas.llm.client import triage

    assert triage(text).category == cat


@pytest.mark.integration
def test_real_call():
    from atlas.llm.client import triage

    assert triage("Cannot log in to SSO since this morning").category == "access"
