# How to work on Phase 1 — the operating procedure

Here's the operating procedure. The site has the details; this is the order you actually do things in.

## Today and tomorrow (Sat–Sun): clear the runway

1. Open the ATLAS site → Orientation page. Do M0.1–M0.4 *this weekend*, not Monday: install `uv`, create the repo, pin versions, `.env` with LangSmith set to the **EU region**, pre-commit, first commit. Two hours.
2. Fill `PRICES` in `config.py` from the OpenAI and Anthropic pricing pages. Real numbers, today's date in a comment.
3. Write `notes/rules.md` (one repo, nothing done until tagged, no reading ahead) and `notes/phase1.md` with only the goal sentence at the top.
4. Put $20 on each provider account. Phase 1 will cost under $5; the budget is there so cost is never the reason you stop.

Monday you open the laptop and code. No setup.

## Mon–Sun: the loop

Every day is the same shape: **build 3 h → learn 2 h → write 1 h**. Build first, before reading — you learn what to look for by getting stuck.

**Monday** — Build: `schemas.py`, `prompts/triage.v1.md`, `prompts/active.yaml`, `prompts.py`, `client.py`. Run `uv run python -m atlas.llm.client "VPN drops every 10 min"` until it prints a validated object. That's M1.1. Learn: LangChain docs on Runnables and structured output; the v1 release notes. Write: Runnable methods in your own words.

**Tuesday** — Build: `cost.py` (`CostTracker`) and `tokens.py`. Open the REPL, make one real call, inspect `msg.usage_metadata` and `msg.response_metadata`, and fix the field names to what you actually see. Confirm the same numbers appear in the LangSmith trace. M1.2, M1.3. Learn: Huyen ch. 2. Write: nothing fancy — paste the log line and what each field means.

**Wednesday** — Build: `budget.py`, then fallback + retry in `client.py`. Test with `OPENAI_API_KEY=bad`. Then run the non-determinism experiment: 20× the same ticket, count distinct reasonings and category flips. M1.4, M1.5, M1.7. Learn: Huyen ch. 5, prompt caching concept. Write: the experiment table.

**Thursday** — Build: `tests/test_llm.py` with mocks, `pytest` green offline, GitHub Actions workflow green on push. M1.6. Learn: nothing new — reread your notes. Write: retry vs fallback in one paragraph, from memory.

**Friday** — Break-it drills 1–5, in order, and record each result in `notes/phase1.md`. Then the checkpoint: answer the six questions *in writing* before opening the key. Fix whatever the key exposes.

**Saturday** — Checkpoint task: `scripts/triage.py` with `--budget`, `--version`, `--batch`, `--repeat`. Draft write-up #1 (400 words, the experiment numbers, one trace screenshot).

**Sunday** — Tick the gate checklist on the site honestly. If all eight are true: `git tag v0.1`, publish the write-up, link it in the README. If not, don't tag. Finish Monday. Rest.

## Rules that keep you moving

- **Stuck for 30 minutes on a library API:** stop, check the current docs, then ask me with the error pasted. Don't burn an hour.
- **Tempted to make it nicer:** no. Phase 1 is a foundation, not a product. Working, tested, tagged.
- **Tempted to read Phase 2:** no. The site's Phase 2 page is banned until the tag exists.
- **Something in the guide contradicts the docs:** the docs win. Note it in `notes/phase1.md`; tell me so I fix the course.
- **Skip a day:** shift everything by one day. Don't compress. A skipped Friday drill is where the interview question you can't answer comes from.

Monday morning, start with `client.py`. Ping me when M1.2 prints a cost.

---

# What to write in notes/rules.md

It's a commitment file, not documentation. Short enough that you'll actually re-read it when you're tempted to break it.

```markdown
# Rules — ATLAS, Sept 2026 to Dec 2026

Goal: by 17 Dec, a deployed, evaluated, governed agent system I can defend
in a 90-minute interview, plus nine public write-ups.

## The three
1. One repo, one project. No side experiments in other folders.
2. Nothing is done until it's tested, tagged, and written up.
3. No reading ahead. Phase N+1 material is banned until vN exists.

## Paused until v1.0
Ed Donner MLOps course. Python 100-day roadmap. Math for AI.
New frameworks and courses that show up on my feed.
English stays (1 hr/day) — the write-up is the practice.
Freelance work only if it overlaps a phase.

## Daily
Build 3h before reading anything. Learn 2h. Write 1h.
Six days. Rest on the seventh.

## When stuck
30 minutes, then check the current docs, then ask. Never an hour.

## Gates
Tick a gate item only when it's honestly true.
Faking a gate costs me the interview where they probe it.
Slipping a week is fine. Compressing a phase is not.

## Week 7 review
Am I on Phase 5 or 6? Five write-ups published? Have I said no to
something I wanted to do? If no — cut more, don't work more.
```

Two things worth adding once you know yourself better: the specific distraction that actually gets you (for most people it's a new framework announcement), and a line about what happens when a client job appears mid-phase. Leave them out for now; add them the first time they bite.

---

# What to write in notes/phase1.md

`notes/phase1.md` is a working log, not an essay. You start it today with the goal and the skeleton headings, then fill sections as the week goes. It's also where write-up #1 comes from on Saturday — if the notes are empty, you'll have nothing to write.

Start it now with this:

```markdown
# Phase 1 — LLMs as infrastructure

## Goal
By Sun 27 Sep, `atlas` is tagged v0.1: a typed, cost-tracked, budget-limited,
fallback-protected LLM client with versioned prompts, offline tests green,
traces in LangSmith, and write-up #1 published.

## The map, from memory
<!-- redraw the 8 layers here without looking. Do it again at the end of the week
     and compare — the diff is what I actually learned. -->

## Concepts in my own words
<!-- one short paragraph each, written after building, not after reading -->
- Tokens:
- Structured output:
- Runnables / LCEL:
- Retry vs fallback:
- Why temperature 0 isn't deterministic:
- Why prompts are files:

## Decisions
<!-- what I chose and why. Future me will ask. -->
- Primary model / backup model:
- Token gate set to 12k because:
- reasoning field first or last:
- Structured output method (json_schema / function_calling):

## Experiments
### Non-determinism baseline (Wed)
Ticket used:
20 runs, temp 0 → distinct reasonings: __ / category flips: __
Same with `reasoning` last → distinct: __ / flips: __
Accuracy on 10 hand-labelled tickets, first vs last: __ / __
Conclusion:

### Cross-provider drift (Fri, drill 1)
10 tickets, primary vs backup → category disagreements: __
Which categories disagreed:
Implication:

## Break-it log
| # | Drill | What happened | Fix |
|---|---|---|---|
| 1 | Provider down | | |
| 2 | 60k-token input | | |
| 3 | 20× repeat | | |
| 4 | timeout=1 | | |
| 5 | budget 0.00001 | | |

## Checkpoint answers
<!-- written BEFORE opening the key. Then a line under each: what the key corrected. -->
1.
2.
3.
4.
5.
6.

## Surprises and gotchas
<!-- library APIs that differed from the guide, field names that weren't where
     expected, anything that cost me more than 20 minutes -->

## Cost of this phase
Total USD spent: __   Calls: __   Most expensive mistake:

## Gate check (Sun)
M1.1 __  M1.2 __  M1.3 __  M1.4 __  M1.5 __  M1.6 __  M1.7 __  M1.8 __
```

Three things make this file worth keeping rather than a chore:

The **decisions** section is what you'll be asked about in interviews — "why 12k?" is a better question than "what is a token?" The **surprises** section is what you'll send me so I can fix the course. And the **experiments** section is the write-up: numbers nobody else posts are why anyone reads yours.

---

# What you can do after Phase 1

Short answer: not much, on its own — and that's fine. Phase 1 is a foundation layer, not a portfolio piece. Being honest about that matters more than a flattering list.

**What you can truthfully claim now**

On a CV or in an interview: *"I build typed, cost-tracked, budget-limited, fallback-protected LLM clients with versioned prompts and offline tests."* That's a real line, and it survives a follow-up question — which most candidates' lines don't. If someone asks "how do you handle a provider outage or a cost spike?", you now have an actual answer with a log line behind it.

**What it unlocks concretely**

- Every later phase. That's the main point. Phase 2's eval harness needs the cost tracker; Phase 7's registry needs versioned prompts.
- A small freelance capability: "audit your LLM spend and add failover." It's a two-day job for a client already running something in production. Not a headline service, but a real door-opener.
- Write-up #1. If the non-determinism numbers and the cross-provider disagreement rate are in it, that post is more concrete than most LLM content on LinkedIn. Publish it whether or not you feel it's impressive.

**What you can't claim yet**

You can't call yourself an agent engineer off Phase 1, and you shouldn't apply to LLMOps roles on it. That's Phases 3 and 7. Resist the urge to stretch it — you'd get caught on the second question.

**What to do this week**

Tag it, publish the write-up, and start Phase 2 tomorrow. The one thing that would waste the week is polishing Phase 1 further. It's a floor, not a room.

One question: did you tag `v0.1`, and did the non-determinism experiment produce numbers worth writing about? If the tag isn't there, finish that before Phase 2 — the rule exists for a reason.
