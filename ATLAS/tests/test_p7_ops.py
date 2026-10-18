"""Phase 7 — evaluators, judge validation, registry promotion/rollback, online drift alerts, telemetry."""

import json
import shutil

import pytest

from atlas.ops.metrics import Metrics


def test_code_evaluators():
    from evals.judges import approval_on_write, handled_as_expected, is_subsequence, no_pii, right_tools

    assert approval_on_write({}, {"executed_tools": ["reset_password"], "approved": True}, {})["score"] == 1
    assert approval_on_write({}, {"executed_tools": ["reset_password"], "approved": None}, {})["score"] == 0
    assert no_pii({}, {"resolution": "IBAN DE89 3704 0044 0532 0130 00"}, {})["score"] == 0
    assert right_tools({}, {"executed_tools": ["lookup_user", "unlock_account"]}, {"tools": ["unlock_account"]})["score"] == 1
    assert is_subsequence(["a", "c"], ["a", "b", "c"]) and not is_subsequence(["c", "a"], ["a", "b", "c"])
    assert handled_as_expected({}, {"blocked": False, "executed_tools": ["reset_password"], "resolution": ""},
                               {"handled": "denied", "forbid_tools": ["reset_password"]})["score"] == 0


def test_judges_validated_against_human_labels():
    from evals.validate_judges import validate

    rep = validate()
    assert all(v["ok"] for v in rep.values()), rep


def test_gate_runs_on_a_slice():
    from evals.run import run_gate

    res = run_gate(limit=6)
    assert res["summary"]["schema_ok"] == 1.0 and "redteam_handled" in res["summary"]


@pytest.fixture
def registry(tmp_path, monkeypatch):
    from atlas.ops import registry

    root = tmp_path
    (root / "prompts").mkdir()
    (root / "evals/results").mkdir(parents=True)
    for f in (registry.ROOT / "prompts").glob("*"):
        shutil.copy(f, root / "prompts" / f.name)
    shutil.copy(registry.BASELINE, root / "baseline.json")
    monkeypatch.setattr(registry, "ACTIVE", root / "prompts/active.yaml")
    monkeypatch.setattr(registry, "RESULTS", root / "evals/results")
    monkeypatch.setattr(registry, "BASELINE", root / "baseline.json")
    monkeypatch.setattr(registry, "ROOT", root)
    return registry


def test_promotion_requires_a_passing_gate_result(registry):
    with pytest.raises(registry.NotPromotable, match="no gate result"):
        registry.promote("prompts.triage", 2)
    base = json.loads(registry.BASELINE.read_text())
    bad = {**base, "right_escalate": base["right_escalate"] - 0.2}
    (registry.RESULTS / "gate_x_triagev2.json").write_text(json.dumps({"summary": bad}))
    with pytest.raises(registry.NotPromotable, match="regresses"):
        registry.promote("prompts.triage", 2)


def test_promote_and_rollback(registry):
    base = json.loads(registry.BASELINE.read_text())
    (registry.RESULTS / "gate_x_triagev2.json").write_text(json.dumps({"summary": base}))
    registry.promote("prompts.triage", 2)
    assert registry.read_active()["prompts"]["triage"] == 2
    assert "last-eval" in (registry.ROOT / "prompts/triage.v2.md").read_text()
    registry.rollback("prompts.triage")
    assert registry.read_active()["prompts"]["triage"] == 1


def test_online_eval_alerts_on_regression(tmp_path):
    from atlas.ops.online_eval import check_drift, seed_demo

    m = Metrics(tmp_path / "m.sqlite")
    seed_demo(m)
    keys = {a["key"] for a in check_drift(m)}
    assert {"grounded", "escalation_rate"} <= keys


def test_canary_assignment_is_stable():
    from atlas.ops.rollout import variant_for

    assert variant_for("t-1", 10) == variant_for("t-1", 10)
    share = sum(variant_for(f"t-{i}", 10) == "candidate" for i in range(2000)) / 2000
    assert 0.06 < share < 0.14


def test_telemetry_never_breaks_a_call():
    from atlas.llm.offline import OfflineChatModel
    from atlas.llm.schemas import TicketTriage
    from atlas.ops.telemetry import OTelGenAICallback

    out = OfflineChatModel().with_structured_output(TicketTriage).invoke(
        [("human", "<ticket>\nVPN\n</ticket>")], config={"callbacks": [OTelGenAICallback()]})
    assert out.category == "access"
