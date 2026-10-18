"""P7 — validate every LLM judge against human labels BEFORE it gates anything.

TPR = of the cases humans labelled FAIL, how many did the judge fail?   (catches real problems)
TNR = of the cases humans labelled PASS, how many did the judge pass?   (doesn't cry wolf)
"Agreement" hides a judge that passes everything on a mostly-passing dataset. A judge below 0.85 on either
gets its rubric fixed first.

    uv run python -m evals.validate_judges
"""

import json
from datetime import date
from pathlib import Path

from evals.judges import LLM_JUDGES

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "evals/datasets/judge_labels_v1.jsonl"
MIN = 0.85


def validate() -> dict:
    rows = [json.loads(x) for x in LABELS.read_text().splitlines() if x.strip()]
    report = {}
    for judge in LLM_JUDGES:
        tp = tn = fp = fn = 0
        disagreements = []
        for r in rows:
            human = r["labels"][judge.__name__]
            got = judge({"ticket_text": r["ticket_text"]}, {"resolution": r["resolution"], "context_text": r["context"]},
                        {"escalate": r["should_escalate"]})["score"]
            if human == 0 and got == 0:
                tp += 1
            elif human == 1 and got == 1:
                tn += 1
            elif human == 1 and got == 0:
                fp += 1
                disagreements.append(r["id"])
            else:
                fn += 1
                disagreements.append(r["id"])
        tpr = tp / (tp + fn) if tp + fn else 1.0
        tnr = tn / (tn + fp) if tn + fp else 1.0
        report[judge.__name__] = {"tpr": round(tpr, 3), "tnr": round(tnr, 3), "n": len(rows),
                                  "ok": tpr >= MIN and tnr >= MIN, "disagreements": disagreements}
    return report


def main():
    rep = validate()
    print("| judge | TPR | TNR | status | disagreements |\n|---|---|---|---|---|")
    for k, v in rep.items():
        print(f"| {k} | {v['tpr']:.2f} | {v['tnr']:.2f} | {'✅' if v['ok'] else '❌ fix rubric'} | {', '.join(v['disagreements'])} |")
    out = ROOT / f"evals/results/judge_validation_{date.today()}.json"
    out.write_text(json.dumps(rep, indent=1))
    raise SystemExit(0 if all(v["ok"] for v in rep.values()) else 1)


if __name__ == "__main__":
    main()
