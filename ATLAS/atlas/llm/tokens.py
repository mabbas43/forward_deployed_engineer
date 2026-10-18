"""P1 — the token gate. Count before sending; a 40-page attachment fails fast here, not after 60 s and $0.80."""

from functools import lru_cache

from atlas.logging import get_logger

log = get_logger()


class InputTooLarge(Exception): ...


LIMITS = {"gpt-4.1-mini": 1_000_000, "gpt-4.1": 1_000_000, "claude-sonnet-4-5": 200_000}
GATE = 12_000  # ATLAS policy: a ticket never needs more than this; anything larger is an attachment problem


@lru_cache(maxsize=8)
def _encoder(model: str):
    try:
        import tiktoken

        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            return tiktoken.get_encoding("o200k_base")
    except Exception as e:  # no network to fetch the BPE file, etc. — degrade to an estimate, never crash
        log.warning("tokenizer_unavailable", model=model, err=type(e).__name__)
        return None


def count(text: str, model: str = "gpt-4.1-mini") -> int:
    """Exact for OpenAI models (tiktoken). Anthropic tokenizes differently — use its count-tokens endpoint for exact."""
    enc = _encoder(model)
    if enc is None:
        return max(1, len(text) // 4)  # ~4 chars/token in English; German is worse (~3–3.5)
    return len(enc.encode(text, disallowed_special=()))


def assert_fits(system: str, user: str, model: str, reserve_output: int = 512, gate: int = GATE) -> int:
    n = count(system, model) + count(user, model) + reserve_output
    if n > gate or n > LIMITS.get(model, 128_000):
        raise InputTooLarge(f"{n} tokens exceeds gate {gate}")
    return n
