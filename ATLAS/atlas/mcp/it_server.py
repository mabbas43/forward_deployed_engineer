"""P4 — the IT systems MCP server (remote, authenticated, Streamable HTTP).

Whoever owns the data owns the server: IT owns `atlas-it`. The tenant comes from the verified token, never from
a tool argument — so the model cannot ask for another tenant's data. Role checks happen HERE (who may act on
IT's data) and again at the client (what this agent may even see). Defense in depth.

    uv run python -m atlas.mcp.it_server            # http://127.0.0.1:8001/mcp
    curl -i -X POST http://127.0.0.1:8001/mcp       # → 401 missing_token
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from atlas.config import ROOT
from atlas.mcp import backends
from atlas.mcp.auth import BearerAuthMiddleware, current_principal, require_role

POLICY_DIR = ROOT / "data/corpus/acme/it"
MAX_CHARS = 2000  # payload discipline: tool results are context

mcp = FastMCP("atlas-it", stateless_http=True, json_response=True, host="127.0.0.1", port=8001)


@mcp.tool()
def lookup_user(email: str) -> dict:
    """Account status, groups and last login for a company user, by company email.
    Returns {"status": "active|locked|disabled", "groups": [...], "last_login": iso8601} or {"error": "user_not_found"}."""
    p = require_role({"helpdesk", "it_support"})
    return backends.lookup_user(p["tenant"], email)


@mcp.tool()
def reset_password(email: str, idempotency_key: str) -> dict:
    """Send a password-reset link to the user's registered company email. Requires idempotency_key; the same key
    never sends twice. Returns {"sent": bool, "request_id": str}. Only it_support may call this."""
    p = require_role({"it_support"})
    return backends.reset_password(p["tenant"], email, idempotency_key)


@mcp.tool()
def unlock_account(email: str, idempotency_key: str) -> dict:
    """Unlock a company account locked after failed sign-in attempts. Returns {"unlocked": bool}."""
    p = require_role({"helpdesk", "it_support"})
    return backends.unlock_account(p["tenant"], email, idempotency_key)


@mcp.tool()
def reset_mfa(email: str, idempotency_key: str) -> dict:
    """Reset a user's MFA registration after identity verification; the manager is notified.
    Returns {"mfa_reset": bool}. Only it_support may call this."""
    p = require_role({"it_support"})
    return backends.reset_mfa(p["tenant"], email, idempotency_key)


@mcp.tool()
def request_access(email: str, resource: str, idempotency_key: str) -> dict:
    """Create an access request for a shared drive or application, routed to the data owner.
    Returns {"request_id": str, "status": "pending_owner_approval"}."""
    p = current_principal()
    return backends.request_access(p["tenant"], email, resource, idempotency_key)


@mcp.resource("policy://it/{name}")
def policy(name: str) -> str:
    """IT policy document by name, e.g. 'password-policy', 'vpn-guide'."""
    path = (POLICY_DIR / f"{Path(name).name}.md")  # Path(name).name: no ../ traversal
    return path.read_text()[:MAX_CHARS] if path.exists() else "not found"


def app():
    """The ASGI app: Streamable HTTP endpoint behind bearer-token auth."""
    return BearerAuthMiddleware(mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app(), host="127.0.0.1", port=8001)
