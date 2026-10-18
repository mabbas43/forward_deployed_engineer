"""P6 — the policy engine. Deny by default; every decision is a structured, audited event.

Capability separation (CaMeL line of work): the model only *proposes* steps. This module — reading policy,
verified identity and taint — decides whether each one may run, and whether a human must approve it.
"""

import time
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel

from atlas.config import ROOT

POLICY_PATH = ROOT / "atlas/governance/policy.yaml"
_cache: dict = {"mtime": 0.0, "policy": {}}


def load_policy(path: Path = POLICY_PATH) -> dict:
    """Hot-reloads on change, so flipping a kill switch takes effect without a deploy."""
    m = path.stat().st_mtime
    if m != _cache["mtime"]:
        _cache.update(mtime=m, policy=yaml.safe_load(path.read_text()))
    return _cache["policy"]


@dataclass
class Ctx:
    tenant: str
    user_hash: str
    role: str
    user_email: str = ""
    trace_id: str = ""

    def audit_fields(self) -> dict:
        d = asdict(self)
        d.pop("user_email")
        return d


class Decision(BaseModel):
    allow: bool
    reason: str
    requires_approval: bool = False


def evaluate_tool(policy: dict, tool: str, ctx: Ctx, state: dict | None = None, args: dict | None = None,
                  quota_count: int = 0) -> Decision:
    state, args = state or {}, args or {}
    if policy.get("kill_switch", {}).get("tools") or policy.get("kill_switch", {}).get("agent"):
        return Decision(allow=False, reason="kill_switch")
    rule = policy.get("tools", {}).get(tool)
    if rule is None:
        return Decision(allow=False, reason="not_in_policy")  # deny by default
    if ctx.role not in rule.get("roles", []):
        return Decision(allow=False, reason=f"role:{ctx.role}")
    if rule.get("deny_if_tainted") and state.get("taint"):
        return Decision(allow=False, reason="tainted_context")
    target = (args.get("email") or "").lower()
    tg = policy.get("targets", {})
    if target and target in tg.get("protected_accounts", []) and tool != "lookup_user":
        return Decision(allow=False, reason="protected_account")
    if target and ctx.role in tg.get("self_service_roles", []) and target != ctx.user_email.lower():
        return Decision(allow=False, reason="not_own_account")
    if (lim := rule.get("max_per_day_per_user")) and quota_count >= lim:
        return Decision(allow=False, reason="quota")
    return Decision(allow=True, reason="ok", requires_approval=bool(rule.get("requires_approval")))


def evaluate_route(policy: dict, route: str) -> dict:
    if route in policy.get("kill_switch", {}).get("routes", []):
        return {"auto_act": False, "escalate": True, "reason": "kill_switch"}
    return policy.get("routes", {}).get(route, {"auto_act": True})


def model_allowed(policy: dict, model: str) -> bool:
    allowed = policy.get("models", {}).get("allowed", [])
    return any(model == a or model.startswith(a) for a in allowed)


class ResidencyViolation(Exception): ...


def check_residency(policy: dict, base_urls: dict[str, str | None]) -> None:
    """Refuse to start if eu_residency is on and a provider points at a non-EU endpoint.

    `base_urls` maps provider → configured base URL (None = provider default, which is US for OpenAI/Anthropic).
    """
    if not policy.get("models", {}).get("eu_residency"):
        return
    bad = {p: u for p, u in base_urls.items()
           if p != "offline" and not (u and (".openai.azure.com" in u or "eu-central-1" in u or "eu." in u))}
    if bad:
        raise ResidencyViolation(f"eu_residency=true but non-EU endpoints configured: {bad}")


def today_bucket() -> str:
    return time.strftime("%Y-%m-%d")
