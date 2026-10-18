"""P6 — PII detection, German edition. Redact on input; BLOCK on output.

Deterministic recognizers (regex + checksums) run everywhere and are fast. With `uv sync --extra pii`,
Microsoft Presidio is used for broader NER-based detection, with these recognizers added to it.
A partially redacted IBAN is still a leak signal — that's why output uses block, not redact.
"""

import re
from dataclasses import dataclass

from atlas.logging import get_logger

log = get_logger()


@dataclass
class Finding:
    entity_type: str
    start: int
    end: int
    value: str


def _iban_ok(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    n = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(n) % 97 == 1


def _luhn(s: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", s)][::-1]
    return len(d) >= 13 and sum(x if i % 2 == 0 else (x * 2 - 9 if x * 2 > 9 else x * 2) for i, x in enumerate(d)) % 10 == 0


PATTERNS: dict[str, tuple[re.Pattern, callable]] = {
    "EMAIL_ADDRESS": (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), lambda s: True),
    "IBAN_CODE": (re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b"), _iban_ok),
    "CREDIT_CARD": (re.compile(r"\b(?:\d[ -]?){13,19}\b"), _luhn),
    # Steuer-ID: 11 digits, first digit non-zero. (Personalausweis numbers: add a recognizer as a Level 2 task.)
    "DE_ID": (re.compile(r"\b[1-9]\d{1}\s?\d{3}\s?\d{3}\s?\d{3}\b"), lambda s: len(re.sub(r"\D", "", s)) == 11),
    "PHONE_NUMBER": (re.compile(r"(?<![\w@])(?:\+49|0049|0)\s?\(?\d{2,5}\)?[\s/-]?\d{3,}[\s-]?\d{0,6}\b"),
                     lambda s: 9 <= len(re.sub(r"\D", "", s)) <= 15),
    "MEDICAL": (re.compile(r"\b(diagnos\w*|depression|burn-?out|cancer|pregnan\w*|chemotherapy|HIV|Krankheit\w*)\b",
                           re.I), lambda s: True),
}
ALL = list(PATTERNS)


def findings(text: str, entities: list[str] | None = None) -> list[Finding]:
    out: list[Finding] = []
    for ent in entities or ALL:
        pat, valid = PATTERNS[ent]
        for m in pat.finditer(text):
            if valid(m.group(0)):
                out.append(Finding(ent, m.start(), m.end(), m.group(0)))
    # IBANs contain long digit runs that look like phones/cards: drop overlaps with a validated IBAN
    ibans = [(f.start, f.end) for f in out if f.entity_type == "IBAN_CODE"]
    out = [f for f in out if f.entity_type == "IBAN_CODE" or not any(s <= f.start < e for s, e in ibans)]
    return sorted(out, key=lambda f: f.start)


def redact(text: str, entities: list[str] | None = None) -> str:
    for f in sorted(findings(text, entities), key=lambda f: -f.start):
        text = text[: f.start] + f"<{f.entity_type}>" + text[f.end :]
    return text


def contains(text: str, entities: list[str] | None = None) -> list[str]:
    return sorted({f.entity_type for f in findings(text, entities)})


def iban_detector(text: str) -> list[dict]:
    """Adapter for LangChain's PIIMiddleware(detector=...) — returns PIIMatch-shaped dicts."""
    return [{"type": "iban", "value": f.value, "start": f.start, "end": f.end}
            for f in findings(text, ["IBAN_CODE"])]


def pseudonymize(text: str, entities: list[str] | None = None) -> tuple[str, dict[str, str]]:
    """Reversible redaction: the model sees `<EMAIL_ADDRESS_1>`, tools receive the real value via the mapping.

    The mapping lives only in graph state (checkpointer — covered by retention and erasure), never in prompts,
    logs, memory or traces.
    """
    mapping: dict[str, str] = {}
    seen: dict[str, str] = {}
    counters: dict[str, int] = {}
    for f in sorted(findings(text, entities), key=lambda f: -f.start):
        tok = seen.get(f.value)
        if tok is None:
            counters[f.entity_type] = counters.get(f.entity_type, 0) + 1
            tok = f"<{f.entity_type}_{counters[f.entity_type]}>"
            seen[f.value] = tok
            mapping[tok] = f.value
        text = text[: f.start] + tok + text[f.end :]
    return text, mapping


def restore(value: str, mapping: dict[str, str]) -> str:
    for tok, real in mapping.items():
        value = value.replace(tok, real)
    return value
