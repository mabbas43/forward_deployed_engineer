"""Fake internal systems: a user directory, a password-reset service, an invoice ledger.

Both the local P3 tools and the P4 MCP servers call these, so the agent code doesn't change when the
integration moves behind MCP. Write operations dedupe on idempotency keys — the property durable execution
forces onto every side-effecting tool (a node that crashed re-runs on resume).
"""

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from atlas.config import settings

USERS = {
    "acme": {
        "anna.schmidt@acme-logistics.de": {"name": "Anna Schmidt", "status": "active", "groups": ["warehouse"],
                                            "last_login": "2026-10-09T07:58:00Z"},
        "ben.mueller@acme-logistics.de": {"name": "Ben Müller", "status": "locked", "groups": ["finance"],
                                           "last_login": "2026-10-08T16:12:00Z"},
        "clara.wagner@acme-logistics.de": {"name": "Clara Wagner", "status": "active", "groups": ["hr"],
                                            "last_login": "2026-10-10T08:30:00Z"},
        "deniz.kaya@acme-logistics.de": {"name": "Deniz Kaya", "status": "active", "groups": ["it_support"],
                                          "last_login": "2026-10-10T06:45:00Z"},
        "ceo@acme-logistics.de": {"name": "Executive", "status": "active", "groups": ["executives"],
                                  "last_login": "2026-10-10T09:01:00Z"},
    },
    "globex": {
        "sam.lee@globex.example": {"name": "Sam Lee", "status": "active", "groups": ["ops"],
                                   "last_login": "2026-10-09T11:00:00Z"},
    },
}

INVOICES = {
    "acme": {
        "INV-88231": {"supplier": "Nordfracht GmbH", "amount_eur": 4180.0, "payments": ["PAY-1201", "PAY-1288"],
                      "po": "PO-5521"},
        "INV-88310": {"supplier": "PackPro AG", "amount_eur": 920.5, "payments": ["PAY-1302"], "po": "PO-5530"},
    }
}


class WriteLedger:
    """Idempotency ledger for write operations: same key → same result, side effect happens once."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, dict] = json.loads(path.read_text()) if path and path.exists() else {}
        self.side_effects: list[dict] = []  # what actually happened (tests count these)

    def once(self, op: str, key: str, fn) -> dict:
        k = f"{op}:{key}"
        with self._lock:
            if k in self.data:
                return {**self.data[k], "deduplicated": True}
            result = fn()
            self.data[k] = result
            self.side_effects.append({"op": op, "key": key, **result})
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.data))
            return result


ledger = WriteLedger(settings.data_dir / "write_ledger.json")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def lookup_user(tenant: str, email: str) -> dict:
    u = USERS.get(tenant, {}).get(email.lower().strip())
    if not u:
        return {"error": "user_not_found"}
    return {"email": email, "status": u["status"], "groups": u["groups"], "last_login": u["last_login"]}


def reset_password(tenant: str, email: str, idempotency_key: str) -> dict:
    if "error" in lookup_user(tenant, email):
        return {"error": "user_not_found"}
    return ledger.once("reset_password", f"{tenant}:{idempotency_key}",
                       lambda: {"sent": True, "request_id": f"rst-{uuid.uuid4().hex[:8]}", "at": _now(), "email": email})


def unlock_account(tenant: str, email: str, idempotency_key: str) -> dict:
    u = USERS.get(tenant, {}).get(email.lower())
    if not u:
        return {"error": "user_not_found"}

    def do():
        u["status"] = "active"
        return {"unlocked": True, "at": _now(), "email": email}

    return ledger.once("unlock_account", f"{tenant}:{idempotency_key}", do)


def reset_mfa(tenant: str, email: str, idempotency_key: str) -> dict:
    if "error" in lookup_user(tenant, email):
        return {"error": "user_not_found"}
    return ledger.once("reset_mfa", f"{tenant}:{idempotency_key}",
                       lambda: {"mfa_reset": True, "manager_notified": True, "at": _now(), "email": email})


def request_access(tenant: str, email: str, resource: str, idempotency_key: str) -> dict:
    if "error" in lookup_user(tenant, email):
        return {"error": "user_not_found"}
    return ledger.once("request_access", f"{tenant}:{idempotency_key}",
                       lambda: {"request_id": f"acc-{uuid.uuid4().hex[:8]}", "resource": resource,
                                "status": "pending_owner_approval"})


def lookup_invoice(tenant: str, reference: str) -> dict:
    inv = INVOICES.get(tenant, {}).get(reference.upper().strip())
    if not inv:
        return {"error": "invoice_not_found"}
    return {"reference": reference.upper(), **inv, "duplicate_payment": len(inv["payments"]) > 1}


def request_credit_note(tenant: str, reference: str, idempotency_key: str) -> dict:
    inv = lookup_invoice(tenant, reference)
    if "error" in inv:
        return inv
    return ledger.once("request_credit_note", f"{tenant}:{idempotency_key}",
                       lambda: {"requested": True, "supplier": inv["supplier"], "reference": inv["reference"]})
