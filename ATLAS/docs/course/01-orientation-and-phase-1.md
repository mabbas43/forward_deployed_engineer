# ATLAS — Orientation & Phase 1: The Complete Guide
### Goal, milestones, concepts, resources, code, drills. One week. One outcome.

---

## The goal (the only sentence that matters this week)

> **By Sunday, September 27, `atlas` is a git repo with tag `v0.1`: a typed, cost-tracked, budget-limited, fallback-protected LLM client with versioned prompts, passing offline tests, traced in LangSmith — and write-up #1 is published.**

Everything below exists to make that sentence true. If an activity doesn't move it, skip it.

**Why this goal and not "learn LLMs":** the whole course stacks on this layer. A client that can't say what a call cost, can't survive a provider outage, and returns untyped prose will poison every phase after it. Nail it once, never touch it again.

---

# Part 0 — Orientation (Day 1, ~5 hours)

## 0.1 Mindset: you're building a product, not doing a course

Analogy: a course is a gym membership. A project is a marathon with a date. You've done the gym. This week you run.

Three rules you commit to on Day 1, in writing, in `notes/rules.md`:
1. **One repo, one project.** ATLAS. No side experiments in other folders.
2. **Nothing is done until tested, tagged, and written up.**
3. **No reading ahead.** Phase 2 material is banned until `v0.1` exists.

## 0.2 The map — draw it, don't read it

Redraw this from memory before every phase. If you can't, you don't understand the shape yet.

```
Layer 8  Platform      API · queue · tenancy · rate limits · IaC          (P8)
Layer 7  Operations    traces · evals in CI · registry · drift · SLOs      (P7)
Layer 6  Control       guardrails · policy · audit · GDPR/AI Act          (P6)
Layer 5  Adaptation    memory · reflection · routing · feedback           (P5)
Layer 4  Integration   MCP servers/clients                                (P4)
Layer 3  Orchestration LangGraph state machines · tools · HITL            (P3)
Layer 2  Knowledge     ingest · hybrid retrieval · rerank                 (P2)
Layer 1  Model access  clients · structured output · fallbacks · cost     (P1)  ◄── this week
```

**The loop that is LLMOps:** observe → evaluate → change → deploy behind a gate → observe. You can't retrain rented weights. You can only re-prompt, re-route, re-retrieve, re-evaluate. Every phase adds one lever to that loop. Phase 1 gives you the first two: *prompt versions* and *cost/latency observation*.

## 0.3 Environment setup

**M0.1 — Toolchain ready** (done when every command below succeeds)

```bash
# Python via uv (fast, lockfile, no venv fiddling)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version

# project
mkdir atlas && cd atlas && git init
uv init --python 3.12
uv add langchain langchain-core langchain-openai langchain-anthropic langsmith \
       pydantic pydantic-settings structlog tiktoken tenacity python-dotenv
uv add --dev pytest pytest-asyncio pytest-mock ruff mypy pre-commit
uv run python -c "import langchain, langgraph; print('ok')" 2>/dev/null || uv add langgraph
```

**Pin versions now.** Open `pyproject.toml`; every dependency gets `==`. LangChain 1.x moved fast; a floating version will break a lab in Phase 5. `uv lock` produces the lockfile — commit it.

**Pre-commit** (`.pre-commit-config.yaml`): ruff (lint + format), mypy on `atlas/`, a hook that fails if `.env` is staged. Run `pre-commit install`.

**`.env.example`** (commit this; never commit `.env`):
```
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=atlas-dev
LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com   # EU region — Phase 6 will thank you
```

**LangSmith:** create a free account, pick the **EU region** now (you're targeting German clients; data residency is a real question later and migrating projects is a pain). Create project `atlas-dev`.

**M0.2 — Repo skeleton exists** (done when `tree` matches and `uv run pytest` reports 0 tests collected, no errors)

```
atlas/
├── pyproject.toml  uv.lock  .env.example  .pre-commit-config.yaml  README.md
├── atlas/
│   ├── __init__.py
│   ├── config.py          # settings + PRICES
│   └── llm/__init__.py
├── prompts/
├── evals/results/
├── tests/__init__.py
├── notes/rules.md  notes/phase1.md
└── docs/
```

**`atlas/config.py`**:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    openai_api_key: str
    anthropic_api_key: str
    langsmith_api_key: str = ""
    primary_model: str = "gpt-4.1-mini"
    backup_model: str = "claude-sonnet-4-5"
    default_budget_usd: float = 0.05

settings = Settings()

# $ per 1M tokens — copy from provider pricing pages on Day 1; update when they change.
PRICES: dict[str, dict[str, float]] = {
    "gpt-4.1-mini":     {"in": 0.40, "out": 1.60, "cached_in": 0.10},
    "gpt-4.1":          {"in": 2.00, "out": 8.00, "cached_in": 0.50},
    "claude-sonnet-4-5":{"in": 3.00, "out": 15.00, "cached_in": 0.30},
}
```
Verify the numbers against the pricing pages *today*. Wrong prices → wrong every decision in Phase 7.

**M0.3 — Git hygiene** (done when the first commit exists and `git log` shows a conventional message)

- Branch `main`; work on `phase-1`, squash-merge, tag.
- Commit messages: `feat(llm): add structured triage client`, `test(llm): fallback fires on primary error`. This is your public proof of work; make it readable.
- README: three lines now — what ATLAS is, what phase you're on, how to run tests. Grows every Friday.

**M0.4 — Orientation write-up seed** (done when `notes/phase1.md` has the map drawn from memory and the week's goal sentence)

---

# Phase 1 — LLMs as infrastructure, not chatbots (Days 2–7)

## 1.1 Mental model

An LLM API is a **flaky, expensive, non-deterministic database that answers in prose**.

Treat it like a database and every decision this week becomes obvious:

| Database habit | LLM equivalent | ATLAS file |
|---|---|---|
| connection config, pool, timeouts | client config, `timeout`, `max_retries` | `client.py` |
| schema on the result set | structured output (Pydantic) | `schemas.py` |
| read replica for failover | fallback model | `client.py` |
| query cost / EXPLAIN | token count + price table | `cost.py`, `tokens.py` |
| slow-query log | structured logs + LangSmith traces | `cost.py` |
| query in version control | prompt files with headers | `prompts/` |
| don't `SELECT *` | token gate, trimmed inputs | `tokens.py` |
| transaction budget | per-request USD budget | `budget.py` |

## 1.2 Concepts — what you must actually understand

### Tokens
The model doesn't see characters or words; it sees **tokens** — subword pieces from a fixed vocabulary (BPE). English runs ~4 chars/token; German runs worse (~3–3.5, longer compounds split more); JSON and code are token-heavy because of punctuation. Consequences:
- **Cost** is tokens in + tokens out, at different prices. Output is typically 4–5× the input price. A verbose `reasoning` field costs real money at scale.
- **Latency** ≈ fixed overhead + (output tokens × per-token time). Input tokens are cheap in time (parallel prefill); output tokens are sequential. Want speed? Ask for less output.
- **Context window** is a hard cap on input + output tokens. Exceed it → error, or silent truncation depending on client. You gate before sending.

Count locally with `tiktoken` for OpenAI models (`encoding_for_model`). Anthropic exposes a count-tokens endpoint. Counts differ per provider — count with the tokenizer of the model you'll call.

### Sampling, temperature, and the determinism myth
The model outputs a probability distribution over the next token; **sampling** picks one. `temperature=0` picks the argmax (greedy) — *less* random, not deterministic: floating-point non-associativity across GPU batches, provider-side model updates under the same name, and tool-call formatting differences all leak variance. You will *measure* this on Day 3 and write the number down. The implication: never test with "run it once, looks right." Test with populations (Phase 7). This week: log the model version/fingerprint on every call so you can later tell "we changed" from "they changed."

### Structured output — the contract
Three mechanisms, all wrapped by `model.with_structured_output(Schema)`:
1. **JSON mode** — model constrained to emit valid JSON; you validate against a schema after.
2. **Tool/function calling** — you define a "tool" whose parameters are your schema; the model "calls" it; the arguments *are* your structured data. Most reliable on most providers.
3. **Native JSON schema / strict mode** — the provider enforces the schema during decoding (OpenAI's strict structured outputs). Best when available.

LangChain picks a default per provider; you can force one with `method="json_schema" | "function_calling" | "json_mode"`. Know which you're on — the failure modes differ (json_mode can return valid JSON that violates your schema; function_calling can hallucinate optional fields).

Rules for schemas that survive production:
- **Enums as `Literal[...]`**, never free strings. `category: Literal["billing","access","bug","hr","other"]`.
- **Field descriptions** — they're injected into the prompt the model sees. Write them like instructions.
- **Constraints** — `ge=1, le=5`. Pydantic validates; a violation raises, which your retry/fallback can catch.
- **Keep reasoning short** and *last* in the schema? No — put `reasoning` **first**. Models fill fields in order; reasoning before the verdict improves the verdict (cheap chain-of-thought). Test this on Day 3.

### Runnables and LCEL — the composition layer
Everything in LangChain core implements `Runnable`: prompts, models, output parsers, retrievers, and your own functions (`RunnableLambda`). Every Runnable has:
- `invoke(x)` / `ainvoke(x)` — one input
- `batch([x...])` / `abatch` — many inputs, concurrent (`max_concurrency` in config)
- `stream(x)` / `astream` — incremental output
- `astream_events` — structured event stream (tokens, tool starts, etc.) — Phase 3/8

Compose with `|`: `prompt | model | parser`. Each stage gets tracing, batching, streaming, retries, and fallbacks *because the interface is uniform*. `RunnableParallel` fans out; `RunnablePassthrough` forwards; `.with_config()` attaches tags/metadata/callbacks.

**`RunnableConfig`** is how you pass per-call context: `callbacks`, `tags`, `metadata`, `run_name`, `max_concurrency`, `recursion_limit`. Tags like `prompt:triage.v1` and `tenant:acme` are what let you filter LangSmith later. Start tagging now.

### Retries vs fallbacks vs timeouts
- **Timeout** — give up on *this* call after N seconds. Set per model (`timeout=20`). Without it, one stuck call blocks a worker forever (Phase 8).
- **Retry** — same call again. For transient failures: 429 rate limit, 5xx, network blips, timeouts. `max_retries=2` on the client, or `.with_retry(stop_after_attempt=3)` on the Runnable. Exponential backoff with jitter (the SDK does this).
- **Fallback** — a *different* call. For persistent failures: provider down, model deprecated, content refusal, schema validation failure after retries. `.with_fallbacks([backup])`.

They compose: `primary.with_retry() .with_fallbacks([backup.with_retry()])`. Retry inside, fallback outside. A fallback to a *different provider* is the only real protection against a provider outage — and it introduces the schema-drift problem you'll test on Day 3.

### Cost accounting
`cost = tokens_in × price_in + tokens_out × price_out (+ cached_in × price_cached)`. Sum per call → per request → per tenant → per day. Providers return usage in the response metadata; LangChain surfaces it in `response.usage_metadata` / `llm_output`. A callback handler (`BaseCallbackHandler.on_llm_end`) is the clean place to capture it once for every call in the app.

**Prompt caching** — providers cache long, stable prompt prefixes (system prompt, few-shots) and charge a fraction for cached input tokens. Structure prompts as *stable prefix + variable suffix* from day one so Phase 8 can turn caching on with no rewrite.

### Prompts are code
- Live in `prompts/<name>.v<N>.md`. Never string literals in Python.
- Header: version, owner, date, last-eval, score. Empty now; Phase 7 fills it.
- Changing a prompt = new version file. Old versions stay (reproducibility).
- `prompts/active.yaml` says which version serves. Phase 7's registry writes this file; this week you write it by hand.

### Observability, minimum viable
- **structlog** JSON logs: one `llm_call` event per call with model, tokens, usd, latency, fingerprint, tags.
- **LangSmith** tracing: on via env var, zero code. Every `invoke` becomes a trace with inputs, outputs, tokens, latency. Open it. Click around. This becomes your raw material in Phase 7.

### Testing LLM code
Unit tests must run without network and without money. Techniques:
- **Fake models**: `langchain_core.language_models.fake_chat_models.FakeListChatModel` / `GenericFakeChatModel` return canned responses.
- **Mock the chain**: `pytest-mock` to patch `triage_chain.invoke`.
- **Test the wrapper, not the model**: fallback fires on exception; budget raises; token gate rejects; schema validates; prompt loader picks the active version.
- One **integration test** marked `@pytest.mark.integration`, skipped by default, hits the real API — run manually before tagging.

## 1.3 Resources (ranked, with what to extract)

| # | Resource | Time | Extract this |
|---|---|---|---|
| 1 | **LangChain docs → Concepts: Runnable interface, LCEL, Chat models, Structured output, Callbacks** | 2 h | the Runnable methods table; the three structured-output methods and when LangChain uses each; how to pass config/tags |
| 2 | **`docs.langchain.com/oss/python/releases/langchain-v1`** | 30 m | what moved in 1.x (`langchain-classic`), so import errors don't eat your week |
| 3 | **Chip Huyen, *AI Engineering* ch. 2 (Understanding Foundation Models) + ch. 5 (Prompt Engineering)** | 3 h | sampling & why greedy isn't deterministic; prompt as versioned artifact; the "defensive prompt engineering" section |
| 4 | **OpenAI + Anthropic pricing and rate-limit pages** | 30 m | fill `PRICES`; note cached-input pricing; note your tier's RPM/TPM — that's what trips retries |
| 5 | **`tiktoken` README + the OpenAI tokenizer playground** | 20 m | paste a German ticket, see the token count; paste JSON, see why it's expensive |
| 6 | **LangSmith docs → Tracing quickstart, Concepts (runs, traces, tags)** | 30 m | how tags/metadata surface in the UI; where usage and latency show |
| 7 | **Anthropic docs → Prompt caching** (concept only) | 20 m | prefix-stable prompt structure; you won't enable it yet |
| 8 | Optional: **Karpathy — "Let's build the GPT tokenizer"** (YouTube) | 2 h | only if tokenization still feels like magic after #5 |

Total: ~7.5 h. Fits Days 2–3 Block B. Don't read anything else this week.

## 1.4 Milestones — each with a "done when" test

| Milestone | Deliverable | Done when |
|---|---|---|
| **M1.1 Typed client** | `schemas.py`, `client.py`, `prompts/triage.v1.md`, `prompts/active.yaml` | `uv run python -m atlas.llm.client "VPN drops every 10 min"` prints a validated `TicketTriage` |
| **M1.2 Cost tracking** | `cost.py` | every call logs one `llm_call` JSON line with usd > 0, latency, model, fingerprint; same numbers visible in LangSmith |
| **M1.3 Token gate** | `tokens.py` | a 60k-token input raises `InputTooLarge` before any API call (assert via mock: model never invoked) |
| **M1.4 Budget** | `budget.py` | `triage(text, budget_usd=0.0001)` raises `BudgetExceeded`; the log shows the refused call |
| **M1.5 Fallback + retry** | `client.py` | with `OPENAI_API_KEY=bad`, triage still returns a valid object and the log shows `model=claude…`; test asserts fallback fires on exception |
| **M1.6 Tests + CI** | `tests/test_llm.py`, `.github/workflows/test.yml` | `uv run pytest` green offline; GitHub Actions green on push |
| **M1.7 Non-determinism baseline** | `notes/phase1.md` | 20-run experiment table: distinct reasonings, category flips, at temp 0 |
| **M1.8 Ship** | tag `v0.1`, write-up #1 published | `git tag` lists `v0.1`; write-up link in README |

## 1.5 Day-by-day

| Day | Block A — build (3 h) | Block B — learn (2 h) | Block C (1 h) |
|---|---|---|---|
| **1 Mon** | M0.1–M0.4 setup, first commit | Resources 2, 4, 5 | draw the map from memory; write the goal sentence |
| **2 Tue** | M1.1 typed client + prompt v1 | Resources 1, 6 | notes: Runnable methods in your own words |
| **3 Wed** | M1.2 cost + M1.3 tokens; M1.7 experiment | Resource 3 (ch. 2) | notes: the experiment table |
| **4 Thu** | M1.4 budget + M1.5 fallback/retry | Resource 3 (ch. 5), 7 | notes: retry vs fallback in one paragraph |
| **5 Fri** | M1.6 tests + CI | Break-it drills 1–4 | checkpoint questions, written |
| **6 Sat** | Checkpoint task (CLI script) | re-read your notes; fix gaps | write-up #1 draft |
| **7 Sun** | polish, README, tag `v0.1` | — | publish write-up; rest |

## 1.6 Lab — the code

**`atlas/llm/schemas.py`**
```python
from typing import Literal
from pydantic import BaseModel, Field

Category = Literal["billing", "access", "bug", "hr", "other"]

class TicketTriage(BaseModel):
    reasoning: str = Field(description="One sentence: the key evidence for the category and urgency.")
    category: Category = Field(description="billing=invoices/payments; access=logins/permissions/VPN; "
                                           "bug=software defects; hr=leave/payroll/people matters; other=none of these")
    urgency: int = Field(ge=1, le=5, description="1=can wait a week; 3=this week; 5=production down or security risk")
    needs_human: bool = Field(description="True if a person must review before any action is taken "
                                          "(security, HR, legal, or ambiguous requests).")
```

**`prompts/triage.v1.md`**
```
<!-- version: 1 | owner: abbas | created: 2026-09-22 | last-eval: — | score: — -->
You are the triage step of ATLAS, an internal IT/HR support system for a mid-size company.

Read the ticket and classify it. Be conservative: when unsure between two categories choose the
one that would route to the safer team; when unsure about urgency, round down unless there is a
security or outage signal.

Never take action. Never ask the user questions. Output only the structured classification.
```

**`prompts/active.yaml`**
```yaml
triage: 1
```

**`atlas/llm/prompts.py`**
```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2] / "prompts"

def active_version(name: str) -> int:
    return yaml.safe_load((ROOT / "active.yaml").read_text())[name]

def load(name: str, version: int | None = None) -> tuple[str, int]:
    v = version or active_version(name)
    text = (ROOT / f"{name}.v{v}.md").read_text()
    body = text.split("-->", 1)[1].strip() if text.startswith("<!--") else text
    return body, v
```

**`atlas/llm/tokens.py`**
```python
import tiktoken

class InputTooLarge(Exception): ...

LIMITS = {"gpt-4.1-mini": 1_000_000, "gpt-4.1": 1_000_000, "claude-sonnet-4-5": 200_000}
GATE = 12_000   # ATLAS policy: a ticket never needs more than this; anything larger is an attachment problem

def count(text: str, model: str = "gpt-4.1-mini") -> int:
    try: enc = tiktoken.encoding_for_model(model)
    except KeyError: enc = tiktoken.get_encoding("o200k_base")
    return len(enc.encode(text))

def assert_fits(system: str, user: str, model: str, reserve_output: int = 512) -> int:
    n = count(system, model) + count(user, model) + reserve_output
    if n > GATE or n > LIMITS.get(model, 128_000):
        raise InputTooLarge(f"{n} tokens exceeds gate {GATE}")
    return n
```

**`atlas/llm/cost.py`**
```python
import time, structlog
from langchain_core.callbacks import BaseCallbackHandler
from atlas.config import PRICES

log = structlog.get_logger()

class BudgetExceeded(Exception): ...

def usd(model: str, tokens_in: int, tokens_out: int, cached_in: int = 0) -> float:
    p = PRICES.get(model, {"in": 0, "out": 0, "cached_in": 0})
    return ((tokens_in - cached_in) * p["in"] + cached_in * p.get("cached_in", p["in"]) + tokens_out * p["out"]) / 1e6

class CostTracker(BaseCallbackHandler):
    """Logs every LLM call; enforces a per-request USD budget."""
    def __init__(self, budget_usd: float | None = None, tags: list[str] | None = None):
        self.total_usd = 0.0; self.calls = 0
        self.budget_usd = budget_usd; self.tags = tags or []

    def on_llm_start(self, serialized, prompts, **kw):
        self._t0 = time.perf_counter()
        if self.budget_usd is not None and self.total_usd >= self.budget_usd:
            raise BudgetExceeded(f"spent {self.total_usd:.5f} of {self.budget_usd}")

    def on_chat_model_start(self, serialized, messages, **kw):
        self.on_llm_start(serialized, [], **kw)

    def on_llm_end(self, response, **kw):
        gen = response.generations[0][0]
        msg = getattr(gen, "message", None)
        um = getattr(msg, "usage_metadata", None) or {}
        meta = getattr(msg, "response_metadata", {}) or {}
        model = meta.get("model_name") or meta.get("model") or "unknown"
        i, o = um.get("input_tokens", 0), um.get("output_tokens", 0)
        cached = (um.get("input_token_details") or {}).get("cache_read", 0)
        cost = usd(model, i, o, cached)
        self.total_usd += cost; self.calls += 1
        log.info("llm_call", model=model, tokens_in=i, tokens_out=o, cached_in=cached,
                 usd=round(cost, 6), total_usd=round(self.total_usd, 6),
                 latency_ms=int((time.perf_counter() - self._t0) * 1000),
                 fingerprint=meta.get("system_fingerprint"), tags=self.tags)
        if self.budget_usd is not None and self.total_usd > self.budget_usd:
            raise BudgetExceeded(f"spent {self.total_usd:.5f} of {self.budget_usd}")
```
Where usage lives varies slightly by provider and LangChain version — inspect a real response in the REPL on Day 3 (`msg.usage_metadata`, `msg.response_metadata`) and adjust the field names once.

**`atlas/llm/client.py`**
```python
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from atlas.config import settings
from atlas.llm.schemas import TicketTriage
from atlas.llm.prompts import load
from atlas.llm.tokens import assert_fits
from atlas.llm.cost import CostTracker

def build_triage_chain():
    primary = ChatOpenAI(model=settings.primary_model, temperature=0, timeout=20, max_retries=2)
    backup  = ChatAnthropic(model=settings.backup_model, temperature=0, timeout=20, max_retries=2)
    p = primary.with_structured_output(TicketTriage, method="json_schema")
    b = backup.with_structured_output(TicketTriage)
    return p.with_fallbacks([b])

triage_chain = build_triage_chain()

def triage(ticket: str, *, budget_usd: float | None = None, prompt_version: int | None = None,
           tags: list[str] | None = None) -> TicketTriage:
    system, v = load("triage", prompt_version)
    assert_fits(system, ticket, settings.primary_model)
    tracker = CostTracker(budget_usd=budget_usd if budget_usd is not None else settings.default_budget_usd,
                          tags=[f"prompt:triage.v{v}", *(tags or [])])
    return triage_chain.invoke(
        [("system", system), ("human", ticket)],
        config={"callbacks": [tracker], "tags": tracker.tags, "run_name": "triage"},
    )

if __name__ == "__main__":
    import sys, json
    print(json.dumps(triage(" ".join(sys.argv[1:])).model_dump(), indent=2))
```

**`scripts/triage.py`** (checkpoint task) — argparse: `--budget`, `--version`, `--batch file.jsonl`, `--repeat N`. `--repeat 20` runs the same ticket 20× via `.batch()` and prints distinct reasonings and category flips — that's M1.7.

**`tests/test_llm.py`**
```python
import pytest
from unittest.mock import MagicMock
from atlas.llm.schemas import TicketTriage
from atlas.llm.tokens import assert_fits, InputTooLarge
from atlas.llm.cost import CostTracker, BudgetExceeded, usd

def test_schema_rejects_bad_category():
    with pytest.raises(Exception):
        TicketTriage(reasoning="x", category="spam", urgency=3, needs_human=False)

def test_token_gate_blocks_large_input():
    with pytest.raises(InputTooLarge):
        assert_fits("sys", "word " * 20_000, "gpt-4.1-mini")

def test_usd_math():
    assert usd("gpt-4.1-mini", 1_000_000, 0) == pytest.approx(0.40)

def test_budget_blocks_second_call():
    t = CostTracker(budget_usd=0.0)
    t.total_usd = 0.01
    with pytest.raises(BudgetExceeded):
        t.on_llm_start({}, [])

def test_fallback_fires(monkeypatch):
    from atlas.llm import client
    primary = MagicMock(); primary.invoke.side_effect = RuntimeError("openai down")
    backup  = MagicMock(); backup.invoke.return_value = TicketTriage(
        reasoning="r", category="access", urgency=3, needs_human=False)
    from langchain_core.runnables import RunnableLambda
    chain = RunnableLambda(primary.invoke).with_fallbacks([RunnableLambda(backup.invoke)])
    monkeypatch.setattr(client, "triage_chain", chain)
    out = client.triage("VPN drops", budget_usd=1.0)
    assert out.category == "access"; backup.invoke.assert_called_once()

@pytest.mark.integration
def test_real_call():
    from atlas.llm.client import triage
    assert triage("Cannot log in to SSO since this morning").category == "access"
```
`pyproject.toml`: `[tool.pytest.ini_options] markers = ["integration"]` and `addopts = "-m 'not integration'"`.

**`.github/workflows/test.yml`** — checkout, `uv sync`, `uv run ruff check`, `uv run pytest`. No secrets needed; integration tests are skipped.

## 1.7 Break it — Day 5

1. **Provider down.** `OPENAI_API_KEY=bad uv run python -m atlas.llm.client "reset my password"`. Fallback fires? Log shows Claude? Now compare 10 tickets on primary vs backup: do categories agree? Record disagreement rate — that's schema drift across providers.
2. **Oversized input.** Paste a 60k-token log dump. `InputTooLarge` before any spend? Check LangSmith — there must be *no* trace.
3. **Non-determinism.** `--repeat 20` on one ambiguous ticket. Count distinct reasonings and any category flips. Then move `reasoning` to the *end* of the schema and repeat. Which order is more stable? Which more accurate on 10 hand-labelled tickets? Write both numbers down.
4. **Timeout.** Set `timeout=1`. Does a timeout trigger retry, then fallback? Or just fail? Understand the difference between a timeout error and an API error in the SDK's retry logic.
5. **Budget.** `--budget 0.00001`. Refused cleanly with a readable error?

## 1.8 Checkpoint — Day 5/6

Write answers in `notes/phase1.md` before opening the key.

1. Why can `with_structured_output` + a fallback silently change behavior when both calls "succeed"?
2. p95 latency doubled overnight, no deploy. Four causes; the log field confirming each.
3. When is `.batch()` the wrong tool for 500 tickets?
4. Retry vs fallback — define, and why you need both.
5. Why does `reasoning` go first in the schema? What's the cost of that choice?
6. Where does a cost figure become *wrong* if you forget prompt caching?

**Task:** `scripts/triage.py` with `--budget`, `--version`, `--batch`, `--repeat`; a demo in the write-up of it refusing a request over budget and of a fallback firing.

<details><summary>Answer key</summary>

1. Providers implement structured output differently (strict schema vs. tool-call emulation vs. JSON mode); enum casing, optional-field omission, and reasoning style differ; downstream routing changes while both calls return valid objects. Fix: `Literal` enums, post-validation, and an eval set run against *both* models.
2. Provider degradation (`latency_ms` up, `model` unchanged); fallback firing constantly (`model` = backup); longer user inputs (`tokens_in` up); retries multiplying (add `attempt`/`retries` to the log); rate-limit 429s in error logs.
3. Need per-item isolation and progress, or 500 concurrent calls exceed your TPM/RPM tier → bounded-concurrency async loop or a queue (Phase 8).
4. Retry = same call for transient errors (429/5xx/timeout). Fallback = different call for persistent failure (outage, refusal, schema failure). Retry-only stalls on outages; fallback-only pays a model switch for every blip.
5. Fields are generated in order; reasoning before the verdict acts as a short chain-of-thought and improves accuracy. Cost: more output tokens (the expensive ones) and slightly higher latency. Keep it to one sentence.
6. Input cost: cached tokens bill at a fraction; if you charge full price you overstate cost, which in Phase 7/8 makes the "route to cheaper model" decision wrong.
</details>

## 1.9 Write-up #1 (Day 6–7, 400 words)

Title idea: *"Treating the LLM like a database: cost, schema, failover."* Include: the mental-model table, the non-determinism experiment numbers, the primary-vs-backup disagreement rate, one screenshot of a LangSmith trace with tags, and the `BudgetExceeded` demo. End with what Phase 2 is.

## 1.10 Gate

You may tag `v0.1` when *every* row of the milestone table is true, `uv run pytest` is green, CI is green, and the write-up is public.

Gate sentence: **"I build typed, cost-tracked, budget-limited, fallback-protected LLM clients with versioned prompts, offline tests, and traces — and I've measured the variance and the cross-provider drift."**

If any part of that sentence is a stretch, you're not done. Finish it. Then Phase 2.
