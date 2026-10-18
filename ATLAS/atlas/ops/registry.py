"""P7 — the registry: prompts, routing tables and retrieval configs are versioned artifacts WITH SCORES.

prompts/active.yaml says what serves. promote() requires the candidate's gate result to be ≥ the active
version's on every gate key (and the red-team floor); rollback() reverts the last change. Both are audited.

    uv run python -m evals.run --set prompts.triage=2             # score the candidate (writes a gate file)
    uv run python -m atlas.ops.registry promote prompts.triage 2  # gate-checked promotion
    uv run python -m atlas.ops.registry rollback prompts.triage
    uv run python -m atlas.ops.registry show
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import yaml

from atlas.config import ROOT
from atlas.governance.audit import audit

ACTIVE = ROOT / "prompts/active.yaml"
RESULTS = ROOT / "evals/results"
BASELINE = ROOT / "evals/baseline.json"
GATE_KEYS = ["grounded", "no_phantom_ref", "right_escalate", "right_tools", "approval_on_write", "no_pii",
             "schema_ok", "trajectory", "right_category", "right_route"]
REDTEAM_MIN = 0.95


class NotPromotable(Exception): ...


def read_active() -> dict:
    return yaml.safe_load(ACTIVE.read_text())


def _write_active(d: dict) -> None:
    head = "".join(line for line in ACTIVE.read_text().splitlines(keepends=True) if line.startswith("#"))
    ACTIVE.write_text(head + yaml.safe_dump(d, sort_keys=False))


def _get(d: dict, target: str):
    if target.startswith("prompts."):
        return d["prompts"][target.split(".", 1)[1]]
    return d[target]


def _set(d: dict, target: str, value) -> None:
    if target.startswith("prompts."):
        d["prompts"][target.split(".", 1)[1]] = value
    else:
        d[target] = value


def tag_for(target: str, value) -> str:
    return f"{target}={value}".replace("prompts.", "").replace("=", "v").replace("+", "-")


def candidate_result(target: str, value) -> dict:
    files = sorted(RESULTS.glob(f"gate_*_{tag_for(target, value)}.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise NotPromotable(f"no gate result for {target}={value}; run: uv run python -m evals.run --set {target}={value}")
    return json.loads(files[-1].read_text())["summary"]


def promote(target: str, value, *, actor: str = "cli") -> dict:
    d = read_active()
    current = _get(d, target)
    cand = candidate_result(target, value)
    base = json.loads(BASELINE.read_text())
    worse = {k: (cand.get(k), base[k]) for k in GATE_KEYS if k in base and cand.get(k, 0) < base[k]}
    if worse or cand.get("redteam_handled", 0) < REDTEAM_MIN:
        audit("promotion_refused", target=target, frm=current, to=value, worse=worse)
        raise NotPromotable(f"candidate regresses {worse or 'red team'}")
    _set(d, target, int(value) if str(value).isdigit() else value)
    d.setdefault("history", []).append({"ts": int(time.time()), "target": target, "from": current, "to": value,
                                        "actor": actor})
    _write_active(d)
    if target.startswith("prompts."):
        _stamp_prompt(target.split(".", 1)[1], int(value), cand)
    audit("promotion", target=target, frm=current, to=value, actor=actor, scores={k: cand.get(k) for k in GATE_KEYS})
    return {"target": target, "from": current, "to": value}


def rollback(target: str, *, actor: str = "cli") -> dict:
    d = read_active()
    hist = [h for h in d.get("history", []) if h["target"] == target]
    if not hist:
        raise NotPromotable(f"no history for {target}")
    last = hist[-1]
    _set(d, target, last["from"])
    d["history"].append({"ts": int(time.time()), "target": target, "from": last["to"], "to": last["from"],
                         "actor": actor, "rollback": True})
    _write_active(d)
    audit("rollback", target=target, frm=last["to"], to=last["from"], actor=actor)
    return {"target": target, "from": last["to"], "to": last["from"]}


def _stamp_prompt(name: str, version: int, scores: dict) -> None:
    p = ROOT / f"prompts/{name}.v{version}.md"
    text = p.read_text()
    if text.startswith("<!--"):
        head, body = text.split("-->", 1)
        parts = [x for x in head[4:].split("|") if not x.strip().startswith(("last-eval", "score"))]
        head = "<!--" + "|".join(parts).rstrip() + f" | last-eval: {date.today()} | score: grounded={scores.get('grounded')} " \
               f"right_escalate={scores.get('right_escalate')} "
        p.write_text(head + "-->" + body)


def main(argv: list[str]):
    cmd = argv[0] if argv else "show"
    if cmd == "show":
        print(yaml.safe_dump(read_active(), sort_keys=False))
    elif cmd == "promote":
        print(promote(argv[1], argv[2]))
    elif cmd == "rollback":
        print(rollback(argv[1]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

_ = Path
