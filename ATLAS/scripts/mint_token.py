"""Dev JWTs. Prod: tokens come from your IdP (OAuth 2.1).

    uv run python scripts/mint_token.py anna.schmidt@acme-logistics.de acme it_support [--aud atlas-api|atlas-it]
"""

import argparse

from atlas.mcp.auth import mint_token

ap = argparse.ArgumentParser()
ap.add_argument("sub")
ap.add_argument("tenant")
ap.add_argument("role", choices=["employee", "helpdesk", "it_support", "finance", "dpo"])
ap.add_argument("--aud", default="atlas-api")
a = ap.parse_args()
print(mint_token(a.sub, a.tenant, a.role, aud=a.aud))
