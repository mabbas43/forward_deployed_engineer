"""P4 — the client side is where governance lives.

A server may expose 40 tools; this agent should see 6. For every tool the client:
1. allow-lists by (role, server, tool name)                          — least privilege, fewer wrong picks
2. pins the manifest: sha256(name + description + schema) must match  — tool descriptions are UNTRUSTED input
   atlas/mcp/manifest.lock.json; a changed description is refused     (a compromised server can inject
   until a human reviews it and re-runs scripts/lock_manifest.py       instructions through them)
3. wraps the call with an audit event (principal, args hash, outcome, latency)

The identity passed to the IT server is the *ticket submitter's*, not a service account.
"""

import asyncio
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

from langchain_core.tools import StructuredTool

from atlas.config import ROOT, settings
from atlas.governance.audit import audit
from atlas.logging import get_logger
from atlas.mcp.auth import mint_token

log = get_logger()
LOCK_PATH = ROOT / "atlas/mcp/manifest.lock.json"

ALLOW = {
    "it_support": {"it": {"lookup_user", "reset_password", "unlock_account", "reset_mfa", "request_access"},
                   "kb": {"search_kb"}},
    "helpdesk": {"it": {"lookup_user", "unlock_account"}, "kb": {"search_kb"}},
    "employee": {"it": {"request_access"}, "kb": {"search_kb"}},
}


class ManifestChanged(Exception):
    def __init__(self, server: str, tool: str):
        super().__init__(f"{server}.{tool}: description/schema changed since it was reviewed — refusing to load")
        self.server, self.tool = server, tool


class ServerUnavailable(Exception):
    def __init__(self, server: str, cause: Exception | None = None):
        super().__init__(f"MCP server '{server}' unavailable: {cause!r}")
        self.server = server


def fingerprint(name: str, description: str, schema: dict) -> str:
    blob = json.dumps({"n": name, "d": description or "", "s": schema}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def tool_fingerprint(t) -> str:
    schema = t.args_schema if isinstance(t.args_schema, dict) else t.args_schema.model_json_schema()
    return fingerprint(t.name, t.description, schema)


def load_lock(path: Path = LOCK_PATH) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def servers(principal: dict) -> dict:
    token = mint_token(principal["sub"], principal["tenant"], principal["role"])  # dev; prod: OAuth token exchange
    return {
        "it": {"url": settings.it_mcp_url, "transport": "streamable_http",
               "headers": {"Authorization": f"Bearer {token}"}},
        "kb": {"command": sys.executable, "args": ["-m", "atlas.mcp.kb_server"], "transport": "stdio",
               "cwd": str(ROOT)},
    }


def _args_hash(kw: dict) -> str:
    return hashlib.sha256(json.dumps(kw, sort_keys=True, default=str).encode()).hexdigest()[:12]


class _Loop:
    """One background event loop so sync graph nodes can call async MCP tools."""

    _loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def run(cls, coro, timeout: float = 60):
        if cls._loop is None:
            cls._loop = asyncio.new_event_loop()
            threading.Thread(target=cls._loop.run_forever, daemon=True, name="mcp-loop").start()
        return asyncio.run_coroutine_threadsafe(coro, cls._loop).result(timeout)


def audited(tool, server: str, principal: dict) -> StructuredTool:
    orig = tool.coroutine

    async def run(**kw):
        t0, h = time.perf_counter(), _args_hash(kw)
        try:
            res = await orig(**kw)
            audit("mcp_call", tenant=principal["tenant"], role=principal["role"], tool=tool.name, server=server,
                  args_hash=h, ok=True, latency_ms=int((time.perf_counter() - t0) * 1000))
            return _unwrap(res)
        except Exception as e:
            audit("mcp_call", tenant=principal["tenant"], role=principal["role"], tool=tool.name, server=server,
                  args_hash=h, ok=False, err=type(e).__name__)
            raise

    def run_sync(**kw):
        return _Loop.run(run(**kw))

    return StructuredTool(name=tool.name, description=tool.description, args_schema=tool.args_schema,
                          coroutine=run, func=run_sync, metadata={"server": server})


def _unwrap(res):
    """MCP returns content blocks; give the agent compact structured data."""
    if isinstance(res, tuple):
        res = res[0]
    if isinstance(res, list) and res and isinstance(res[0], dict) and "text" in res[0]:
        texts = [r["text"] for r in res if r.get("type", "text") == "text"]
        try:
            return json.loads(texts[0]) if len(texts) == 1 else [json.loads(t) for t in texts]
        except (json.JSONDecodeError, TypeError):
            return "\n".join(texts)[:2000]
    return res


async def load_tools(role: str, principal: dict, *, lock: dict | None = None,
                     server_names: tuple[str, ...] = ("it", "kb")) -> list[StructuredTool]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    lock = load_lock() if lock is None else lock
    client = MultiServerMCPClient({k: v for k, v in servers(principal).items() if k in server_names})
    out = []
    for server in server_names:
        try:
            tools = await client.get_tools(server_name=server)
        except Exception as e:  # noqa: BLE001 — any connection failure degrades the same way
            raise ServerUnavailable(server, e) from e
        for t in tools:
            if t.name not in ALLOW.get(role, {}).get(server, set()):
                continue  # invisible to this agent
            if lock.get(server, {}).get(t.name) != tool_fingerprint(t):
                raise ManifestChanged(server, t.name)
            out.append(audited(t, server, principal))
    return out


def mcp_tool_loader(principal: dict, *, include_local: bool = True):
    """GraphOptions.tool_loader: MCP tools (sync-callable) + local tools no server provides (e.g. billing)."""
    from atlas.agents.ticket_graph import ToolsUnavailable
    from atlas.agents.tools import TOOLS

    def loader(role: str):
        try:
            remote = _Loop.run(load_tools(role, principal))
        except ServerUnavailable as e:
            raise ToolsUnavailable(e.server) from e
        names = {t.name for t in remote}
        return remote + ([t for t in TOOLS if t.name not in names] if include_local else [])

    return loader
