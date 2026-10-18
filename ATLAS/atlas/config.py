"""Settings + price table. Everything tunable lives here or in prompts/ and policy.yaml — never in code."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # "auto" = use real providers when keys exist, else the offline heuristic model.
    # "offline" = always offline (tests, CI, learning without spending money).
    atlas_provider: str = "auto"

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    langsmith_api_key: str = ""

    primary_model: str = "gpt-4.1-mini"
    backup_model: str = "claude-sonnet-4-5"
    strong_model: str = "gpt-4.1"
    judge_model: str = "gpt-4.1-2025-04-14"  # P7: pin a dated snapshot for judges
    embedding_model: str = "text-embedding-3-small"

    default_budget_usd: float = 0.05
    request_timeout_s: float = 20.0

    data_dir: Path = ROOT / ".atlas"  # local state: vectors, checkpoints, store, audit
    corpus_dir: Path = ROOT / "data" / "corpus"

    jwt_secret: str = "dev-only-change-me-0123456789abcdef"  # P4/P8: HS256 dev tokens; use your IdP's JWKS in prod
    it_mcp_url: str = "http://127.0.0.1:8001/mcp"

    @property
    def online(self) -> bool:
        if self.atlas_provider == "offline":
            return False
        return bool(self.openai_api_key or self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()

# $ per 1M tokens — copy from provider pricing pages and date it. Wrong prices → wrong P7/P8 decisions.
# Verified: <fill in the date you checked>.
PRICES: dict[str, dict[str, float]] = {
    "gpt-4.1-mini": {"in": 0.40, "out": 1.60, "cached_in": 0.10},
    "gpt-4.1": {"in": 2.00, "out": 8.00, "cached_in": 0.50},
    "claude-sonnet-4-5": {"in": 3.00, "out": 15.00, "cached_in": 0.30},
    "text-embedding-3-small": {"in": 0.02, "out": 0.0, "cached_in": 0.02},
    # Offline mode bills at gpt-4.1-mini rates as *simulated* cost so budgets, dashboards and $/ticket
    # behave like production while you learn for free.
    "offline-heuristic": {"in": 0.40, "out": 1.60, "cached_in": 0.10},
}


def price_for(model: str) -> dict[str, float]:
    """Providers return dated names (gpt-4.1-mini-2025-04-14); match on the longest known prefix."""
    if model in PRICES:
        return PRICES[model]
    for name in sorted(PRICES, key=len, reverse=True):
        if model.startswith(name):
            return PRICES[name]
    return {"in": 0.0, "out": 0.0, "cached_in": 0.0}
