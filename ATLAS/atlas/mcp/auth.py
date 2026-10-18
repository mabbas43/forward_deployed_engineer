"""P4 — who is calling? Every MCP call must know the *human* on whose behalf the agent acts.

Dev: HS256 JWTs signed with settings.jwt_secret (mint with scripts/mint_token.py).
Prod: OAuth 2.1 — the MCP server is a resource server; validate signature/expiry/audience against your IdP's
JWKS (Keycloak per the official MCP authorization tutorial). The principal goes into a context var that tools read.
"""

import contextvars
import time

import jwt
from starlette.responses import JSONResponse

from atlas.config import settings

AUDIENCE = "atlas-it"
principal_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar("principal", default=None)


class Forbidden(Exception): ...


def mint_token(sub: str, tenant: str, role: str, ttl_s: int = 3600, aud: str = AUDIENCE) -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "tenant": tenant, "role": role, "aud": aud, "iat": now, "exp": now + ttl_s},
                      settings.jwt_secret, algorithm="HS256")


def verify(token: str, aud: str = AUDIENCE) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience=aud)


def current_principal() -> dict:
    p = principal_var.get()
    if p is None:
        raise Forbidden("no principal")  # tools are never callable anonymously
    return p


def require_role(allowed: set[str]) -> dict:
    p = current_principal()
    if p.get("role") not in allowed:
        raise Forbidden(f"role {p.get('role')} may not call this tool")
    return p


class BearerAuthMiddleware:
    """ASGI middleware: 401 without a valid bearer token; otherwise sets the principal for this request."""

    def __init__(self, app, aud: str = AUDIENCE):
        self.app, self.aud = app, aud

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return await JSONResponse({"error": "missing_token"}, status_code=401)(scope, receive, send)
        try:
            claims = verify(auth.split(" ", 1)[1], self.aud)
        except jwt.ExpiredSignatureError:
            return await JSONResponse({"error": "token_expired"}, status_code=401)(scope, receive, send)
        except jwt.PyJWTError:
            return await JSONResponse({"error": "invalid_token"}, status_code=401)(scope, receive, send)
        tok = principal_var.set(claims)
        try:
            await self.app(scope, receive, send)
        finally:
            principal_var.reset(tok)
