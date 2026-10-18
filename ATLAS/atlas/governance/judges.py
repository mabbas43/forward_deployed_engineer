"""P6 — model-based guardrail: the grounding check (are the resolution's claims supported by context?).

Layer 3 of the guardrail stack: slowest and most expensive, so it runs on write paths and resolutions,
and its verdicts are audited and monitored like error rates.
"""

from pydantic import BaseModel

from atlas.llm import offline
from atlas.llm.providers import structured

PROMPT = """Decide whether every factual claim in <resolution> is supported by <context> or <results>.
Generic next-step statements ("a colleague will follow up") need no support. passes=true only if nothing is
unsupported. Give a one-sentence reason."""


class Grounded(BaseModel):
    passes: bool
    reason: str


def ground_check(resolution: str, context: str, results: str = "") -> Grounded:
    return structured(Grounded, "judge").invoke(
        [("system", PROMPT), ("human", f"<resolution>\n{resolution}\n</resolution>\n<context>\n{context}\n</context>\n"
                                       f"<results>\n{results}\n</results>")], config={"run_name": "ground_check"})


@offline.handles(Grounded)
def _offline_grounded(task: offline.Task) -> dict:
    from evals.metrics import faithfulness_offline

    res = task.section("resolution")
    generic = ("colleague", "follow up", "passed to", "not approved", "has been sent", "unlocked", "was reset",
               "access request", "credit note", "couldn't find", "can't find", "temporarily unavailable")
    claims = ". ".join(s for s in res.split(". ") if not any(g in s.lower() for g in generic))
    f = faithfulness_offline(claims, task.section("context") + "\n" + task.section("results"))
    return {"passes": f >= 0.75, "reason": f"{f:.0%} of factual sentences supported by context."}
