# The LLMOps loop in this repo — observe → evaluate → change → gate → deploy

```
traces/runs ──► error analysis ──► datasets ──► validated judges ──► CI gate ──► registry ──► shadow/canary ──► prod
     ▲                                                                                                       │
     └──────────────────────────────────── online eval + drift alerts ◄─────────────────────────────────────┘
```

| Step | Command | Output |
|---|---|---|
| Retrieval eval (P2) | `uv run python -m evals.rag_eval` | recall@5 / MRR / faithfulness table per config |
| Validate judges (P7) | `uv run python -m evals.validate_judges` | TPR/TNR per judge; fails if < 0.85 |
| Gate (P7) | `uv run python -m evals.run` | PR-comment table; exit 1 on regression |
| Score a candidate | `uv run python -m evals.run --set prompts.triage=2` | `evals/results/gate_<sha>_triagev2.json` |
| Shadow compare | `uv run python -m atlas.ops.rollout shadow prompts.triage=2` | pairwise wins/ties/losses + $/ticket |
| Promote | `uv run python -m atlas.ops.registry promote prompts.triage 2` | refused if any gate key regresses |
| Roll back | `uv run python -m atlas.ops.registry rollback prompts.triage` | one-line revert, audited |
| Optimizer (P5) | `uv run python -m atlas.agents.optimize triage` | `prompts/triage.vN.md` candidate only |
| Online eval | `uv run python -m atlas.ops.online_eval --once` (`--demo` to see an alert) | scores + drift alerts |
| Dashboard | `uv run python -m atlas.ops.dashboard` | per route/day: quality, p95, $/ticket, block, escalation |
| Adaptive curve (P5) | `uv run python -m evals.adaptive_curve` | memory on vs off curve |

**LangSmith.** Set `LANGSMITH_TRACING=true` and the EU endpoint. Every graph run then becomes a trace tagged with
`prompt:<name>.v<N>`, `tenant:<id>`, `ticket:<id>`. The evaluators in `evals/judges.py` use the
`(inputs, outputs, reference_outputs)` signature, so they plug straight into `langsmith.evaluate(...)`.
Upload `evals/datasets/*.jsonl` as versioned datasets.

**Error analysis (do this first, by hand).** Run 100+ tickets, read each trace, and write one line per trace
saying what went wrong. Then categorize and count. Two known failures to start from: `g-008` ("paid INV-88231
double" → triaged as `other`) and `g-026` (doctor's-note question escalated by the HR rule instead of answered as an FAQ).
