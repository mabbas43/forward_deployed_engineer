"""P4 — the knowledge-base MCP server (stdio). Wraps the Phase 2 retriever as one tool.

A good candidate to open-source as a standalone repo: small, tested, documented.

    npx @modelcontextprotocol/inspector uv run python -m atlas.mcp.kb_server
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("atlas-kb")


@mcp.tool()
def search_kb(query: str, tenant: str, k: int = 3) -> dict:
    """Search the company knowledge base (IT policies, HR handbook, runbooks, past tickets).
    Returns {"results": [{"source", "section", "text"}, ...]} with up to k passages; results are limited to the given tenant and
    text is truncated to 800 characters."""
    from atlas.rag.retrieve import get_retriever

    k = max(1, min(k, 8))
    return {"results": [{"source": h.source, "section": h.section, "text": h.text[:800]}
                        for h in get_retriever().retrieve(query, tenant, "helpdesk", k_final=k)]}


if __name__ == "__main__":
    mcp.run(transport="stdio")
