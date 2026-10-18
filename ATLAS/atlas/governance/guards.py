"""P6 — guardrail functions used as graph nodes (and by the API). Three layers, in order:
deterministic code → classifiers → LLM judges. Prompt instructions are layer 0: helpful, never sufficient.
"""

from atlas.governance.injection import score as injection_score
from atlas.governance.judges import ground_check
from atlas.governance.pii import contains, pseudonymize
from atlas.llm.tokens import GATE, count

AI_NOTICE = "\n\n— ATLAS, an AI assistant. Reply \"human\" at any time to reach a person."  # EU AI Act Art. 50
REFUSAL = ("I can't process this request as written. If you need help, describe the problem in your own words "
           "and a colleague will assist you.")
UNAVAILABLE = "ATLAS is temporarily unavailable; your ticket has been queued for a colleague."


def check_input(text: str, policy: dict) -> dict:
    """→ {"blocked", "reason", "text" (pseudonymized), "pii_map", "score"}."""
    if count(text) > GATE:
        return {"blocked": True, "reason": "too_large", "text": text, "pii_map": {}, "score": 0.0}
    s = injection_score(text)
    if s >= policy.get("guards", {}).get("injection_threshold", 0.6):
        return {"blocked": True, "reason": "injection_input", "text": text, "pii_map": {}, "score": s}
    red, mapping = pseudonymize(text, policy["data"]["redact_input"])
    return {"blocked": False, "reason": "ok", "text": red, "pii_map": mapping, "score": s}


def scan_untrusted(items: list[dict], policy: dict, field: str = "text") -> tuple[list[dict], list[dict]]:
    """Indirect-injection scan over retrieved chunks or tool results → (clean, flagged)."""
    thr = policy.get("guards", {}).get("injection_threshold", 0.6)
    clean, flagged = [], []
    for it in items:
        (flagged if injection_score(str(it.get(field, it))) >= thr else clean).append(it)
    return clean, flagged


def check_output(resolution: str, context: str, results: str, policy: dict, *, grounding: bool = True) -> dict:
    """→ {"text", "blocked_entities", "grounded"}. PII in policy.block_output → block the whole message."""
    found = contains(resolution, policy["data"]["block_output"])
    if found:
        return {"text": "The answer contained sensitive data and was withheld. A colleague will follow up securely.",
                "blocked_entities": found, "grounded": None}
    grounded = None
    if grounding:
        v = ground_check(resolution, context, results)
        grounded = v.passes
        if not v.passes:
            resolution += "\n\n(Some statements could not be verified against company documents.)"
    return {"text": resolution, "blocked_entities": [], "grounded": grounded}
