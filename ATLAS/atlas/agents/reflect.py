"""P5 — bounded reflection: plan → critique → (revise | proceed), at most MAX_ITER rounds.

Unbounded reflection is an infinite bill with diminishing returns. Strong models benefit less — measure
per route, and prefer cheap+reflect or strong+no-reflect, whichever is cheaper per unit of quality.
"""

from pydantic import BaseModel, Field

from atlas.agents.steps import parse_step
from atlas.agents.tools import WRITE_TOOLS, describe
from atlas.llm import offline
from atlas.llm.prompts import load
from atlas.llm.providers import run_config as _cfg
from atlas.llm.providers import structured

MAX_ITER = 2


class Critique(BaseModel):
    passes: bool
    issues: list[str] = Field(default_factory=list)
    must_fix: bool = False


def critique(s: dict, tools, callbacks=None) -> Critique:
    system, _ = load("critique")
    human = "\n".join([f"<ticket>\n{s['ticket_text']}\n</ticket>", f"<triage>\n{s.get('triage')}\n</triage>",
                       "<plan>\n" + "\n".join(s.get("plan", [])) + "\n</plan>",
                       f"<tools>\n{describe(tools)}\n</tools>",
                       "<procedures>\n" + "\n".join(s.get("procedures", [])) + "\n</procedures>"])
    return structured(Critique, "cheap").invoke([("system", system), ("human", human)],
                                                config=_cfg("critique", callbacks))


@offline.handles(Critique)
def _offline_critique(task: offline.Task) -> dict:
    tools = {ln.split("(")[0].strip("- ").strip() for ln in task.section("tools").splitlines() if ln.strip()}
    plan = [p for p in task.section("plan").splitlines() if p.strip()]
    issues = []
    if not plan:
        issues.append("The plan is empty.")
    for p in plan:
        kind, tool, args = parse_step(p)
        if kind == "INVALID":
            issues.append(f"Malformed step: {p}")
        elif tool and tool not in tools:
            issues.append(f"Unknown tool: {tool}")
        elif tool in WRITE_TOOLS and kind != "CALL":
            issues.append(f"{tool} has side effects and must be a CALL step")
        elif tool and "email" in (args or {}) and "@" not in args["email"]:
            issues.append(f"{tool} needs a valid email")
    if "'category': 'hr'" in task.section("triage") and any(p.startswith("CALL") for p in plan):
        issues.append("HR tickets must be escalated, not acted on.")
    return {"passes": not issues, "issues": issues, "must_fix": bool(issues)}
