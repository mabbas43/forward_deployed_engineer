"""P3/P5 — planning and resolution writing.

Context order matters (P5 context engineering): task → constraints → procedures → few-shot cases →
retrieved context → critique. Recalled memories compete with documents for the attention budget.
"""

import re

from pydantic import BaseModel, Field

from atlas.agents.steps import parse_step
from atlas.agents.tools import BY_NAME, WRITE_TOOLS, describe
from atlas.llm import offline
from atlas.llm.offline import first_email, has_any, words
from atlas.llm.prompts import load
from atlas.llm.providers import run_config as _cfg
from atlas.llm.providers import structured
from atlas.rag.generate import best_sentences, format_context


class Plan(BaseModel):
    rationale: str = Field(description="One sentence: why this plan resolves the ticket.")
    steps: list[str] = Field(description="Ordered steps, each 'READ: tool(arg=value)', 'CALL: tool(...)' or 'ANSWER: ...'.")


class Resolution(BaseModel):
    text: str = Field(description="The message the employee reads, with [source] citations.")
    citations: list[str] = Field(default_factory=list)
    escalated: bool = Field(description="True if a human must follow up.")


def format_cases(cases: list[dict]) -> str:
    return "\n".join(f"- ticket: {c['ticket'][:220]} | plan: {' ;; '.join(c['plan'])} | rating: {c.get('rating')}"
                     for c in cases)


def plan_messages(s: dict, tools) -> list[tuple[str, str]]:
    system, _ = load("plan")
    parts = [f"<ticket>\n{s['ticket_text']}\n</ticket>",
             f"<requester>\n{s.get('user_email', '')}\n</requester>",
             f"<triage>\n{s.get('triage', {})}\n</triage>",
             f"<tools>\n{describe(tools)}\n</tools>"]
    if s.get("procedures"):
        parts.append("<procedures>\n" + "\n".join(f"- {p}" for p in s["procedures"]) + "\n</procedures>")
    if s.get("recalled_cases"):
        parts.append(f"<cases>\n{format_cases(s['recalled_cases'])}\n</cases>")
    if s.get("avoid_cases"):
        parts.append(f"<avoid>\n{format_cases(s['avoid_cases'])}\n</avoid>")
    parts.append(f"<context>\n{format_context(s.get('context', []))}\n</context>")
    if s.get("critique") and not s["critique"].get("passes", True):
        parts.append("<critique>\n" + "\n".join(f"- {i}" for i in s["critique"].get("issues", [])) + "\n</critique>")
    return [("system", system), ("human", "\n".join(parts))]


def make_plan(s: dict, tools=None, callbacks=None) -> Plan:
    tools = tools or list(BY_NAME.values())
    return structured(Plan, "primary").invoke(plan_messages(s, tools),
                                              config=_cfg("plan", callbacks))


def write_resolution(s: dict, callbacks=None) -> Resolution:
    system, _ = load("respond")
    results = "\n".join(f"- {r.get('tool')}: {r.get('result')}" for r in s.get("tool_results", []))
    human = "\n".join([
        f"<ticket>\n{s['ticket_text']}\n</ticket>",
        f"<plan>\n{chr(10).join(s.get('plan', []))}\n</plan>",
        f"<approved>\n{s.get('approved')}\n</approved>",
        f"<escalated>\n{bool(s.get('escalated'))}\n</escalated>",
        f"<results>\n{results}\n</results>",
        f"<context>\n{format_context(s.get('context', []))}\n</context>",
    ])
    return structured(Resolution, "primary").invoke([("system", system), ("human", human)],
                                                    config=_cfg("respond", callbacks))


# ---- offline heuristics ---------------------------------------------------------------------------------
# The planner's keyword rules are deliberately *narrow*: unusual phrasings fall through to ANSWER-only plans.
# Episodic memory (recalled, well-rated cases) is what fills those gaps — which is exactly the effect the
# Phase 5 adaptive curve measures.

INV = re.compile(r"\bINV-\d+\b", re.I)


def _base_plan(ticket: str, email: str, triage: str, tools: set[str]) -> list[str]:
    t = ticket.lower()
    if "'category': 'hr'" in triage:
        return ["ANSWER: This is an HR matter; it has been passed to HR, who will contact you."]
    if "password" in t and has_any(t, ["reset", "forgot", "expired"]):
        return [f"READ: lookup_user(email={email})", f"CALL: reset_password(email={email})"]
    if "locked" in t and "account" in t:
        return [f"READ: lookup_user(email={email})", f"CALL: unlock_account(email={email})"]
    if "mfa" in words(t):
        return [f"READ: lookup_user(email={email})", f"CALL: reset_mfa(email={email})"]
    m = re.search(r"access to (?:the )?([\w\- ]+?)(?: drive| folder| share|[.,]|$)", t)
    if m and "request_access" in tools:
        return [f"CALL: request_access(email={email}, resource=\"{m.group(1).strip()} drive\")"]
    ref = INV.search(ticket)
    if ref and has_any(t, ["twice", "duplicate", "double"]):
        r = ref.group(0).upper()
        return [f"READ: lookup_invoice(reference={r})", f"CALL: request_credit_note(reference={r})"]
    return ["ANSWER: Answer from the retrieved company documents."]


def _adapt(plan: list[str], email: str, ticket: str) -> list[str]:
    """Re-target a recalled case's plan at this ticket: swap in this requester's email / invoice ref."""
    ref = INV.search(ticket)
    out = []
    for step in plan:
        step = re.sub(r"email=[^,)]+", f"email={email}", step)
        if ref:
            step = re.sub(r"reference=[^,)]+", f"reference={ref.group(0).upper()}", step)
        out.append(step)
    return out


@offline.handles(Plan)
def _offline_plan(task: offline.Task) -> dict:
    ticket = task.section("ticket")
    pseudo = re.search(r"<EMAIL_ADDRESS_\d+>", ticket)
    email = first_email(ticket) or (pseudo.group(0) if pseudo else None) or task.section("requester") or "unknown@example.com"
    triage = task.section("triage")
    tools = {ln.split("(")[0].strip("- ").strip() for ln in task.section("tools").splitlines() if ln.strip()}
    steps = _base_plan(ticket, email, triage, tools)
    source = "rules"
    if steps[0].startswith("ANSWER") and "'category': 'hr'" not in triage:
        for line in task.section("cases").splitlines():  # few-shot: copy the approach of a similar good case
            m = re.search(r"ticket: (.*) \| plan: (.*) \| rating: (\d)", line)
            if m and int(m.group(3)) >= 4 and len(words(m.group(1)) & words(ticket)) >= 2:
                steps, source = _adapt(m.group(2).split(" ;; "), email, ticket), "recalled case"
                break
    if task.section("critique"):  # revise: drop steps using unknown tools
        steps = [s for s in steps if (parse_step(s)[1] in tools) or s.startswith("ANSWER")] or steps
    if "verify" in task.section("procedures").lower() and any(s.startswith("CALL") for s in steps) \
            and not any("lookup_user" in s for s in steps) and "lookup_user" in tools:
        steps = [f"READ: lookup_user(email={email})", *steps]
    return {"rationale": f"Plan from {source}.", "steps": steps}


def _describe_result(tool: str, result: dict) -> str:
    if "error" in result:
        return f"The step {tool} could not be completed ({result['error']}); a colleague will follow up."
    return {
        "reset_password": "A password-reset link has been sent to your company email.",
        "unlock_account": "Your account has been unlocked; you can sign in again.",
        "reset_mfa": "Your MFA registration was reset. Register your new phone at https://aka.ms/mysecurityinfo.",
        "request_access": "An access request was created and sent to the data owner for approval.",
        "request_credit_note": "Finance has requested a credit note from the supplier for the duplicate payment.",
        "lookup_user": "",
        "lookup_invoice": "",
        "search_kb": "",
    }.get(tool, f"{tool} completed.")


@offline.handles(Resolution)
def _offline_resolution(task: offline.Task) -> dict:
    ticket, ctx = task.section("ticket"), task.section("context")
    escalated = task.section("escalated") == "True"
    approved = task.section("approved")
    lines, cites = [], []
    if escalated:
        lines.append("Your request has been passed to a colleague who will contact you.")
    if approved == "False":
        lines.append("The requested action was not approved, so nothing was changed. A colleague will follow up.")
    for r in task.section("results").splitlines():
        m = re.match(r"- (\w+): (.*)", r)
        if m:
            try:
                import ast

                res = ast.literal_eval(m.group(2))
            except Exception:
                res = {}
            d = _describe_result(m.group(1), res if isinstance(res, dict) else {})
            if d:
                lines.append(d)
    if not escalated:
        for sent, src, score in best_sentences(ticket, ctx, n=2):
            if score >= 0.2:
                lines.append(f"{sent} [{src}]")
                cites.append(src)
    if not lines:
        lines.append("I couldn't find this in the company documents; a colleague from the Service Desk will follow up.")
        escalated = True
    return {"text": " ".join(lines), "citations": sorted(set(cites)), "escalated": escalated}


__all__ = ["Plan", "Resolution", "make_plan", "write_resolution", "WRITE_TOOLS"]
