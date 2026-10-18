"""Plan steps are a tiny, auditable DSL:  READ: tool(a=1, b="x") | CALL: tool(...) | ANSWER: text.

Parsing it in code (not letting the model call tools freely) is capability separation: the model proposes,
code + policy + a human dispose.
"""

import re

STEP = re.compile(r"^\s*(READ|CALL|ANSWER)\s*:\s*(.*)$", re.S)
CALL = re.compile(r"^(\w+)\s*\((.*)\)\s*$", re.S)
ARG = re.compile(r"(\w+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^,]+)")


def parse_step(step: str) -> tuple[str, str | None, dict]:
    """→ (kind, tool, args). ANSWER steps → ("ANSWER", None, {"text": ...}). Malformed → ("INVALID", None, {})."""
    m = STEP.match(step)
    if not m:
        return "INVALID", None, {}
    kind, rest = m.group(1), m.group(2).strip()
    if kind == "ANSWER":
        return kind, None, {"text": rest}
    c = CALL.match(rest)
    if not c:
        return "INVALID", None, {}
    args = {k: v.strip().strip("\"'") for k, v in ARG.findall(c.group(2))}
    return kind, c.group(1), args


def has_writes(plan: list[str]) -> bool:
    return any(parse_step(p)[0] == "CALL" for p in plan)


def tools_in(plan: list[str]) -> list[str]:
    return [t for k, t, _ in map(parse_step, plan) if t]
