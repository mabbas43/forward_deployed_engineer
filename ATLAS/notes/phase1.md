# Phase 1 — LLMs as infrastructure

## Goal
`atlas` is tagged v0.1: a typed, cost-tracked, budget-limited, fallback-protected LLM client with versioned
prompts, offline tests green, traces in LangSmith, and write-up #1 published.

## The map, from memory
<!-- redraw the 8 layers here without looking. Do it again at the end of the week and compare —
     the diff is what I actually learned. -->

## Concepts in my own words
<!-- one short paragraph each, written after building, not after reading -->
- Tokens:
- Structured output:
- Runnables / LCEL:
- Retry vs fallback:
- Why temperature 0 isn't deterministic:
- Why prompts are files:

## Decisions
- Primary model / backup model:
- Token gate set to 12k because:
- reasoning field first or last:
- Structured output method (json_schema / function_calling):

## Experiments
### Non-determinism baseline (`uv run python scripts/triage.py "<ambiguous ticket>" --repeat 20`)
Ticket used:
20 runs, temp 0 → distinct reasonings: __ / category flips: __
Same with `reasoning` last → distinct: __ / flips: __
Accuracy on 10 hand-labelled tickets, first vs last: __ / __
Conclusion:

### Cross-provider drift (drill 1)
10 tickets, primary vs backup → category disagreements: __
Which categories disagreed:
Implication:

## Break-it log
| # | Drill | What happened | Fix |
|---|---|---|---|
| 1 | Provider down (`OPENAI_API_KEY=bad`) | | |
| 2 | 60k-token input | | |
| 3 | 20× repeat | | |
| 4 | timeout=1 | | |
| 5 | `--budget 0.00001` | | |

## Checkpoint answers
<!-- written BEFORE opening the key. Then a line under each: what the key corrected. -->
1.
2.
3.
4.
5.
6.

## Surprises and gotchas
<!-- library APIs that differed from the guide, field names that weren't where expected -->
- (reference build) Passing `config={"callbacks": []}` to a child call cuts it off from the graph's callbacks —
  the per-request budget stopped seeing plan/respond calls. Fixed with `providers.run_config()`.

## Cost of this phase
Total USD spent: __   Calls: __   Most expensive mistake:

## Gate check (Sun)
M1.1 __  M1.2 __  M1.3 __  M1.4 __  M1.5 __  M1.6 __  M1.7 __  M1.8 __
