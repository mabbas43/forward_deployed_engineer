"""P3 — tools that don't hurt you.

- The docstring IS the prompt the model sees when choosing tools. Vague docstring → wrong picks.
- Typed args with descriptions. `tenant` is an *injected* arg: the model never sees or chooses it.
- Compact, structured returns. Recoverable errors come back as {"error": ...} so the model can adapt;
  infra/security failures raise.
- Every write takes an idempotency_key; the backend dedupes on it.

Phase 4 replaces these local tools with MCP-loaded ones (atlas/mcp/client.py) — same names, same contracts.
"""

from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from atlas.mcp import backends

Tenant = Annotated[str, InjectedToolArg]


@tool
def search_kb(query: str, tenant: Tenant, k: int = 3) -> dict:
    """Search the company knowledge base (IT policies, HR handbook, runbooks, past tickets).
    Returns {"results": [{"source", "section", "text"}, ...]} (up to k; text truncated to 800 chars)."""
    from atlas.rag.retrieve import get_retriever

    return {"results": [{"source": h.source, "section": h.section, "text": h.text[:800]}
                        for h in get_retriever().retrieve(query, tenant, "helpdesk", k_final=k)]}


@tool
def lookup_user(email: str, tenant: Tenant) -> dict:
    """Return account status, groups and last login for a company user, by company email.
    Returns {"status": "active|locked|disabled", "groups": [...], "last_login": iso8601} or {"error": "user_not_found"}."""
    return backends.lookup_user(tenant, email)


@tool
def reset_password(email: str, idempotency_key: str, tenant: Tenant) -> dict:
    """Send a password-reset link to the user's registered company email. Side effect.
    Only call when a plan step says CALL: reset_password. Reuse the given idempotency_key on retry so a
    reset is never sent twice. Returns {"sent": bool, "request_id": str} or {"error": "user_not_found"}."""
    return backends.reset_password(tenant, email, idempotency_key)


@tool
def unlock_account(email: str, idempotency_key: str, tenant: Tenant) -> dict:
    """Unlock a company account that is locked after failed sign-in attempts. Side effect.
    Returns {"unlocked": bool} or {"error": "user_not_found"}."""
    return backends.unlock_account(tenant, email, idempotency_key)


@tool
def reset_mfa(email: str, idempotency_key: str, tenant: Tenant) -> dict:
    """Reset a user's MFA registration so they can register a new phone. Side effect; the manager is notified.
    Only after identity verification. Returns {"mfa_reset": bool} or {"error": "user_not_found"}."""
    return backends.reset_mfa(tenant, email, idempotency_key)


@tool
def request_access(email: str, resource: str, idempotency_key: str, tenant: Tenant) -> dict:
    """Create an access request for a shared drive or application, routed to the data owner for approval.
    Side effect. Returns {"request_id": str, "status": "pending_owner_approval"}."""
    return backends.request_access(tenant, email, resource, idempotency_key)


@tool
def lookup_invoice(reference: str, tenant: Tenant) -> dict:
    """Look up a supplier invoice by reference (e.g. INV-88231): supplier, amount, payments, PO,
    and whether it was paid more than once. Returns {"error": "invoice_not_found"} if unknown."""
    return backends.lookup_invoice(tenant, reference)


@tool
def request_credit_note(reference: str, idempotency_key: str, tenant: Tenant) -> dict:
    """Ask Finance to request a credit note from the supplier for a duplicate-paid invoice. Side effect.
    Returns {"requested": bool, "supplier": str}."""
    return backends.request_credit_note(tenant, reference, idempotency_key)


TOOLS = [search_kb, lookup_user, reset_password, unlock_account, reset_mfa, request_access,
         lookup_invoice, request_credit_note]
BY_NAME = {t.name: t for t in TOOLS}
WRITE_TOOLS = {"reset_password", "unlock_account", "reset_mfa", "request_access", "request_credit_note"}
DOMAINS = {
    "access": {"search_kb", "lookup_user", "reset_password", "unlock_account", "reset_mfa", "request_access"},
    "billing": {"search_kb", "lookup_invoice", "request_credit_note"},
}


def describe(tools) -> str:
    """Tool list for prompts: name(args) — first docstring line. Injected args are hidden from the model."""
    lines = []
    for t in tools:
        args = [a for a in t.tool_call_schema.model_json_schema().get("properties", {}) if a != "tenant"]
        kind = "WRITE" if t.name in WRITE_TOOLS else "READ"
        lines.append(f"- {t.name}({', '.join(args)}) [{kind}] — {t.description.splitlines()[0]}")
    return "\n".join(lines)
