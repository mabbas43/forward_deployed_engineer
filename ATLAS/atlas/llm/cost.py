"""P1 — cost is a first-class metric. One callback captures every LLM call in the app.

If you can't state what a request cost in USD, you're not doing LLMOps.
"""

import time

from langchain_core.callbacks import BaseCallbackHandler

from atlas.config import price_for
from atlas.logging import get_logger

log = get_logger()


class BudgetExceeded(Exception): ...


def usd(model: str, tokens_in: int, tokens_out: int, cached_in: int = 0) -> float:
    p = price_for(model)
    return ((tokens_in - cached_in) * p["in"] + cached_in * p.get("cached_in", p["in"]) + tokens_out * p["out"]) / 1e6


class CostTracker(BaseCallbackHandler):
    """Logs one `llm_call` JSON line per call: model, tokens, usd, latency, fingerprint, tags.

    Forgetting cached input (prompt caching) overstates cost — which makes P7/P8 "route to the cheaper model"
    decisions wrong. That's why `cached_in` is tracked separately.
    """

    raise_error = True  # let BudgetExceeded propagate out of the callback

    def __init__(self, tags: list[str] | None = None):
        self.total_usd = 0.0
        self.calls = 0
        self.tags = tags or []
        self.models: list[str] = []
        self._t0: dict = {}

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kw):
        self._t0[run_id] = time.perf_counter()

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kw):
        self.on_llm_start(serialized, [], run_id=run_id, **kw)

    def on_llm_end(self, response, *, run_id=None, **kw):
        gen = response.generations[0][0]
        msg = getattr(gen, "message", None)
        um = getattr(msg, "usage_metadata", None) or {}
        meta = getattr(msg, "response_metadata", {}) or {}
        model = meta.get("model_name") or meta.get("model") or "unknown"
        i, o = um.get("input_tokens", 0), um.get("output_tokens", 0)
        cached = (um.get("input_token_details") or {}).get("cache_read", 0) or 0
        cost = usd(model, i, o, cached)
        self.total_usd += cost
        self.calls += 1
        self.models.append(model)
        t0 = self._t0.pop(run_id, time.perf_counter())
        log.info(
            "llm_call",
            model=model,
            tokens_in=i,
            tokens_out=o,
            cached_in=cached,
            usd=round(cost, 6),
            total_usd=round(self.total_usd, 6),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            fingerprint=meta.get("system_fingerprint"),
            tags=self.tags,
        )
