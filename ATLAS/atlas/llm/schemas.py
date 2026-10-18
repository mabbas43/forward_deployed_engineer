"""P1 — the contract. Structured output turns prose into typed, evaluable data.

Rules: enums as Literal (never free strings), field descriptions written as instructions
(they are injected into the prompt), constraints (ge/le) so violations raise and retry/fallback can catch them,
and `reasoning` FIRST — models fill fields in order, so reasoning-before-verdict is cheap chain-of-thought.
"""

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["billing", "access", "bug", "hr", "other"]


class TicketTriage(BaseModel):
    reasoning: str = Field(description="One sentence: the key evidence for the category and urgency.")
    category: Category = Field(
        description="billing=invoices/payments; access=logins/permissions/VPN/passwords; "
        "bug=software defects; hr=leave/payroll/people matters; other=none of these"
    )
    urgency: int = Field(ge=1, le=5, description="1=can wait a week; 3=this week; 5=production down or security risk")
    needs_human: bool = Field(
        description="True if a person must review before any action is taken (security, HR, legal, or ambiguous)."
    )
