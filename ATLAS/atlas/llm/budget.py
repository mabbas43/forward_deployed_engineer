"""P1 — a per-request USD budget. Pre-checks the *estimated* input cost before each call, re-checks after."""

from atlas.config import price_for
from atlas.llm.cost import BudgetExceeded, CostTracker
from atlas.llm.tokens import count
from atlas.logging import get_logger

log = get_logger()

__all__ = ["BudgetExceeded", "BudgetTracker"]


def _model_from(serialized: dict | None, kw: dict) -> str:
    params = kw.get("invocation_params") or {}
    return params.get("model") or params.get("model_name") or (serialized or {}).get("name") or "unknown"


class BudgetTracker(CostTracker):
    def __init__(self, budget_usd: float, tags: list[str] | None = None):
        super().__init__(tags=tags)
        self.budget_usd = budget_usd

    def _refuse(self, when: str, projected: float):
        log.warning("budget_refused", when=when, spent=round(self.total_usd, 6), projected=round(projected, 6),
                    budget=self.budget_usd, tags=self.tags)
        raise BudgetExceeded(f"projected {projected:.6f} USD exceeds budget {self.budget_usd} ({when}-call)")

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kw):
        text = "\n".join(str(m.content) for batch in messages for m in batch)
        model = _model_from(serialized, kw)
        est = count(text) * price_for(model)["in"] / 1e6
        if self.total_usd + est > self.budget_usd:
            self._refuse("pre", self.total_usd + est)
        super().on_chat_model_start(serialized, messages, run_id=run_id, **kw)

    def on_llm_end(self, response, *, run_id=None, **kw):
        super().on_llm_end(response, run_id=run_id, **kw)
        if self.total_usd > self.budget_usd:
            self._refuse("post", self.total_usd)
