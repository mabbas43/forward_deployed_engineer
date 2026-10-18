"""Regenerate atlas/mcp/manifest.lock.json from the server definitions — the change-control step.

Run ONLY after reviewing a tool description/schema diff. The diff of the lock file goes in the PR.

    uv run python scripts/lock_manifest.py          # write
    uv run python scripts/lock_manifest.py --check  # exit 1 if the lock is stale (CI)
"""

import asyncio
import json
import sys

from atlas.mcp import it_server, kb_server
from atlas.mcp.client import LOCK_PATH, fingerprint


async def compute() -> dict:
    out = {}
    for name, srv in {"it": it_server.mcp, "kb": kb_server.mcp}.items():
        out[name] = {t.name: fingerprint(t.name, t.description, t.inputSchema) for t in await srv.list_tools()}
    return out


def main():
    new = asyncio.run(compute())
    if "--check" in sys.argv:
        old = json.loads(LOCK_PATH.read_text()) if LOCK_PATH.exists() else {}
        if old != new:
            print("manifest.lock.json is stale — review tool changes and re-lock")
            raise SystemExit(1)
        print("manifest lock OK")
        return
    LOCK_PATH.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
    print(f"wrote {LOCK_PATH}")


if __name__ == "__main__":
    main()
