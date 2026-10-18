"""P6 — prompt-injection scoring. Heuristics first (fast, deterministic); a classifier hook for the semantics.

Indirect injection — instructions hidden in KB docs or tool results — is the one that bites agents.
The *user* input guard never sees it, which is why ATLAS also scans retrieved context and tool results.
"""

import re

SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules)", re.I), 0.7),
    (re.compile(r"disregard (your|all|the) (instructions|rules|policy)", re.I), 0.7),
    (re.compile(r"\b(SYSTEM|ADMIN)\s*:", re.I), 0.35),
    (re.compile(r"\byou are now\b|\badmin mode\b|\bdeveloper mode\b|\bjailbreak\b|\bDAN\b"), 0.45),
    (re.compile(r"reveal (your|the) (system )?prompt|print your instructions", re.I), 0.6),
    (re.compile(r"do not ask for (approval|confirmation)|without (approval|asking)", re.I), 0.4),
    (re.compile(r"(reset|delete|disable) (the )?(password|account)s? of (every|all) user", re.I), 0.5),
    (re.compile(r"every user|all users'? (passwords|records|data)", re.I), 0.25),
]


def injection_score(text: str) -> float:
    """0..1. Calibrate the threshold (policy.guards.injection_threshold) on the red-team set — FP rate matters."""
    s = sum(w for p, w in SIGNALS if p.search(text or ""))
    return round(min(1.0, s), 3)


def classifier_score(text: str) -> float | None:
    """Hook for a Prompt-Guard-class model or hosted API. Returns None when not configured."""
    return None


def score(text: str) -> float:
    c = classifier_score(text)
    h = injection_score(text)
    return max(h, c) if c is not None else h
