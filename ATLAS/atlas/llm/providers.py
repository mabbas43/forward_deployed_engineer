"""P1 — one place that decides which model serves which role, with retries inside and fallbacks outside.

    primary.with_retry() ──fallback──► backup.with_retry()

Retry = same call again (429/5xx/timeout). Fallback = a different call (provider down, refusal, schema
failure). A fallback to a *different provider* is the only real protection against an outage — and it
introduces cross-provider schema drift, which you measure in the Phase 1 drills.
"""

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from atlas.config import settings
from atlas.llm.offline import OfflineChatModel

Role = Literal["primary", "backup", "strong", "judge", "cheap"]


def _openai(model: str) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, temperature=0, timeout=settings.request_timeout_s, max_retries=2,
                      api_key=settings.openai_api_key)


def _anthropic(model: str) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, temperature=0, timeout=settings.request_timeout_s, max_retries=2,
                         api_key=settings.anthropic_api_key)


def _model_for(name: str) -> BaseChatModel | None:
    if name.startswith("claude"):
        return _anthropic(name) if settings.anthropic_api_key else None
    return _openai(name) if settings.openai_api_key else None


def chat(role: Role = "primary") -> BaseChatModel:
    """A single chat model for a role. Offline mode (or no keys) → OfflineChatModel."""
    if not settings.online:
        return OfflineChatModel()
    name = {
        "primary": settings.primary_model,
        "cheap": settings.primary_model,
        "backup": settings.backup_model,
        "strong": settings.strong_model,
        "judge": settings.judge_model,
    }[role]
    return _model_for(name) or _model_for(settings.backup_model) or _model_for(settings.primary_model) or OfflineChatModel()


def structured(schema, role: Role = "primary", *, fallback: bool = True) -> Runnable:
    """`model.with_structured_output(schema)` with a cross-provider fallback when both keys exist."""
    if not settings.online:
        return OfflineChatModel().with_structured_output(schema)
    primary = chat(role).with_structured_output(schema)
    if not fallback or role == "judge":  # judges must never silently switch model (judge drift, P7)
        return primary
    backup = _model_for(settings.backup_model)
    if backup is None or settings.backup_model in str(getattr(chat(role), "model", "")):
        return primary
    return primary.with_fallbacks([backup.with_structured_output(schema)])


def run_config(run_name: str, callbacks: list | None = None) -> dict:
    """Child-call config. Never pass `callbacks=[]`: an explicit empty list cuts the call off from the
    callbacks inherited from the graph run — and the per-request budget silently stops seeing it."""
    cfg: dict = {"run_name": run_name}
    if callbacks:
        cfg["callbacks"] = callbacks
    return cfg
