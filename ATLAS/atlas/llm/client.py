"""P1 — the typed, cost-tracked, budget-limited, fallback-protected triage client.

Mental model: an LLM API is a flaky, expensive, non-deterministic database that answers in prose.
Treat it like one: timeouts, retries, a read replica (fallback), a schema on the result, a cost per query,
a slow-query log, and the query (prompt) in version control.

    uv run python -m atlas.llm.client "VPN drops every 10 min"
"""

from langchain_core.runnables import Runnable
from langchain_core.runnables.config import var_child_runnable_config

from atlas.config import settings
from atlas.llm import offline
from atlas.llm.budget import BudgetTracker
from atlas.llm.offline import has_any
from atlas.llm.prompts import load
from atlas.llm.providers import structured
from atlas.llm.schemas import TicketTriage
from atlas.llm.tokens import assert_fits


def build_triage_chain() -> Runnable:
    return structured(TicketTriage, "primary")


triage_chain = build_triage_chain()


def triage(
    ticket: str,
    *,
    budget_usd: float | None = None,
    prompt_version: int | None = None,
    tags: list[str] | None = None,
    tracker: BudgetTracker | None = None,
) -> TicketTriage:
    system, v = load("triage", prompt_version)
    assert_fits(system, ticket, settings.primary_model)  # token gate: fail before any money is spent
    run_tags = [f"prompt:triage.v{v}", *(tags or [])]
    config = {"tags": run_tags, "run_name": "triage", "metadata": {"prompt_version": v}}
    inside_run = var_child_runnable_config.get() is not None
    if tracker is not None or budget_usd is not None or not inside_run:
        # Standalone (CLI/tests) → own budget. Inside a graph run we must NOT pass callbacks explicitly:
        # that would replace the run's inherited callbacks (and its per-request budget would go blind).
        config["callbacks"] = [tracker or BudgetTracker(
            budget_usd if budget_usd is not None else settings.default_budget_usd, tags=run_tags)]
    return triage_chain.invoke([("system", system), ("human", f"<ticket>\n{ticket}\n</ticket>")], config=config)


# ---- offline heuristic (what a good model would do, approximated with rules) -------------------------

_TERMS = {
    "hr": ["leave", "vacation", "payroll", "salary", "sick", "parental", "harass", "complaint about",
           "contract", "urlaub", "gehalt", "overtime", "performance review", "termination", "dismiss"],
    "access": ["password", "login", "log in", "sso", "vpn", "mfa", "2fa", "locked", "access", "permission",
               "sign in", "account", "passwort", "anmelden", "authenticator"],
    "billing": ["invoice", "payment", "billing", "refund", "charge", "rechnung", "credit note",
                "purchase order", "expense", "reimburse"],
    "bug": ["error", "bug", "crash", "broken", "exception", "fails", "not working", "500", "e-", "freez",
            "slow", "timeout", "doesn't load", "won't open", "blue screen", "after the update", "freezes"],
}
_URGENT5 = ["outage", "is down", "production down", "security", "phishing", "breach", "ransomware",
            "all users", "everyone", "malware", "data leak"]
_URGENT4 = ["urgent", "asap", "today", "blocked", "cannot work", "can't work", "deadline"]
_LOW = ["no rush", "when you have time", "question", "curious", "nice to have"]


@offline.handles(TicketTriage)
def _offline_triage(task: offline.Task) -> dict:
    t = task.section("ticket") or task.human
    category = next((c for c in ["hr", "access", "billing", "bug"] if has_any(t, _TERMS[c])), "other")
    urgency = 5 if has_any(t, _URGENT5) else 4 if has_any(t, _URGENT4) else 1 if has_any(t, _LOW) else (
        3 if category in {"access", "bug"} else 2)
    needs_human = category in {"hr", "other"} or (urgency == 5 and has_any(t, ["security", "phishing", "breach"]))
    hit = next((w for w in _TERMS.get(category, []) if w in t.lower()), "no clear signal")
    return {"reasoning": f"Mentions '{hit}', which indicates {category}; urgency {urgency}.",
            "category": category, "urgency": urgency, "needs_human": needs_human}


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(triage(" ".join(sys.argv[1:]) or "VPN drops every 10 min").model_dump(), indent=2))
