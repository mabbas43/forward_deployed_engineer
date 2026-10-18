# ATLAS — an adaptive operations copilot

**A complete, project-based LLMOps & adaptive-agents course in one repo.** ATLAS is the internal copilot of a
400-person German logistics company (Acme Logistics). It answers questions from internal docs, resolves IT/HR/finance
tickets by calling internal systems through MCP, obeys policy-as-code with human approval on every write, gets
measurably better with use, and runs as a queue-backed multi-tenant service on AWS (EU).

The course is in [`docs/course/`](docs/course/README.md). The code is the reference implementation for all nine
phases. **Everything runs offline by default** (deterministic heuristic model, simulated cost), so you can run every
lab, test, eval and drill without API keys. Add keys to `.env` and the same code runs on real models.

```
uv sync                            # Python 3.12, pinned deps (LangChain 1.4, LangGraph 1.2, MCP 1.30)
uv run python scripts/demo.py      # 2-minute tour of every layer
uv run pytest                      # 87 tests, offline, ~10 s
```

## The eight layers → the nine phases

| Phase | Layer | You can say after the gate | Code |
|---|---|---|---|
| 1 | Model access | "I build typed, cost-tracked, budget-limited, fallback-protected LLM clients with versioned prompts and offline tests." | `atlas/llm/` |
| 2 | Knowledge | "…idempotent, tenant-aware ingestion with hybrid retrieval, reranking, query rewriting and corrective RAG — chosen from measured recall/faithfulness." | `atlas/rag/`, `evals/rag_eval.py` |
| 3 | Orchestration | "…durable, resumable LangGraph state machines with typed state, approval gates on writes, idempotent tools and routing tests." | `atlas/agents/ticket_graph.py` |
| 4 | Integration | "…MCP servers over stdio and Streamable HTTP with auth, role gating, client allow-lists, manifest pinning and per-call audit." | `atlas/mcp/` |
| 5 | Adaptation | "…adaptive agents: namespaced episodic/procedural memory, bounded reflection, data-driven routing, tool RAG, supervisor handoffs, an eval-gated optimizer — and the curve." | `atlas/agents/`, `evals/adaptive_curve.py` |
| 6 | Control | "…layered guardrails, policy-as-code with taint-aware write denial, append-only audit, GDPR erasure across every store, EU residency, red-team evals." | `atlas/governance/`, `docs/GOVERNANCE.md` |
| 7 | Operations | "…evaluation-driven development: validated binary judges, CI gate, registry with promote/rollback, shadow/canary, online drift alerts, OTel GenAI." | `evals/`, `atlas/ops/` |
| 8 | Platform | "…multi-tenant, queue-backed, idempotent agent systems with stateless workers, breakers, fair queues, versioned caches, IaC in an EU region." | `atlas/api/`, `infra/` |
| 9 | Capstone | "I have built, evaluated, governed, deployed and documented a production adaptive-agent system — and can defend every layer cold." | `docs/ACCEPTANCE.md` |

## Numbers (offline reference run, 2026-10-11)

Offline numbers measure the *machinery*, not model quality. Rerun with real models for the numbers you publish.

| What | Result | Command |
|---|---|---|
| Retrieval, 40-Q typed golden set | dense recall@5 0.963 → hybrid 1.000; MRR 0.872 → 0.932 with rerank; exact-token recall 0.83 → 1.00 | `make ragEval` |
| End-to-end gate, 30 golden tickets | grounded 1.00 · right_tools 1.00 · right_escalate 0.97 · trajectory 1.00 · approval_on_write 1.00 · ≈ $0.0009/ticket | `make gate` |
| Red team, 60 adversarial cases | 100% handled as expected (injection, indirect/poisoned KB, PII, tool abuse, cross-tenant, DoW, HR) | `make gate` |
| Judge validation vs human labels | grounded TPR 1.00 / TNR 0.92 · no_phantom_ref 1.00/1.00 · right_escalate 1.00/1.00 | `make judges` |
| Adaptive curve, 60 tickets | memory ON 0.75 → 0.95 · memory OFF 0.40 → 0.35 (first 20 → last 20 pass rate) | `make curve` |

## How to use this repo as a course

1. Read [`docs/course/11-strategy-3-months.md`](docs/course/11-strategy-3-months.md) and fill in [`notes/rules.md`](notes/rules.md).
2. For each phase, read `docs/course/0N-phase-N.md`, then **build it yourself on a `phase-N` branch**. Diff against
   the reference only once you're stuck. Log decisions, experiments and break-it drills in `notes/phaseN.md`.
3. A phase is done when its tests pass, its gate sentence is honestly true, you've run `git tag v0.N`, and the write-up is published.
4. Phase 1 operating procedure, day by day: [`docs/course/13-phase-1-operating-procedure.md`](docs/course/13-phase-1-operating-procedure.md).

## Run things

```bash
cp .env.example .env                                   # optional: add keys for real models (EU LangSmith endpoint preset)
uv run python scripts/triage.py "VPN drops every 10 min"            # P1
uv run python scripts/triage.py "printer is weird" --repeat 20       # P1 non-determinism experiment
uv run python scripts/ask.py "What does error E-4471 mean?"          # P2
uv run python scripts/watch.py "My account is locked"                # P3 streaming
uv run python scripts/run_ticket.py "I forgot my password"           # P3 durable approval (kill + resume)
uv run python -m atlas.mcp.it_server                                 # P4 MCP server (HTTP + JWT) on :8001
uvx --from "langgraph-cli[inmem]" langgraph dev                      # LangGraph Studio
uv run python -m evals.adaptive_curve                                # P5
uv run python -m evals.run                                           # P7 gate (exit 1 on regression)
uv run python -m atlas.ops.online_eval --demo                        # P7 drift alert demo
uv run uvicorn atlas.api.main:app --reload                           # P8 API with in-process workers
uv run python scripts/mint_token.py anna.schmidt@acme-logistics.de acme it_support
```

API walk-through:

```bash
TOKEN=$(uv run python scripts/mint_token.py anna.schmidt@acme-logistics.de acme it_support)
curl -s -X POST localhost:8000/tickets -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: k1" \
     -H 'content-type: application/json' -d '{"text":"I forgot my password, please reset it"}'
curl -s localhost:8000/tickets/<id> -H "Authorization: Bearer $TOKEN"            # → awaiting_approval
curl -s -X POST localhost:8000/tickets/<id>/approve -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' -d '{"decision":"approve"}'
curl -N localhost:8000/tickets/<id>/events -H "Authorization: Bearer $TOKEN"     # SSE
```

## Repo map

```
atlas/
  llm/          P1  schemas, prompts loader, token gate, CostTracker, BudgetTracker, providers, offline model, triage
  rag/          P2  ingest (parent-child, tables, manifest), stores, embeddings, hybrid retriever, rerank, rewrite, CRAG
  agents/       P3+P5 state, tools, plan DSL, ticket graph, memory, extractor, reflection, router, tool RAG, supervisor, optimizer
  mcp/          P4  it_server (HTTP+JWT), kb_server (stdio), auth, governed client, manifest.lock.json
  governance/   P6  policy.yaml + engine, PII (German), injection, guards, grounding judge, audit + erasure
  ops/          P7  metrics, registry, online eval, telemetry (OTel GenAI), rollout, dashboard
  api/          P8  FastAPI, queue (fair, visibility, DLQ; SQS adapter), worker, resilience, events, caches
evals/          datasets (rag golden, e2e golden, red team, judge labels), judges, gate, validators, curve
prompts/        versioned prompts + active.yaml (registry-managed) + routes.v1.yaml
data/           corpus (two tenants), red-team docs, ticket stream
infra/          Dockerfile, docker-compose (pgvector, redis, localstack SQS, OTel, Jaeger), Terraform (eu-central-1)
docs/           ARCHITECTURE · GOVERNANCE · THREAT_MODEL · RUNBOOK · LLMOPS · ACCEPTANCE · course/
notes/          rules.md + phase logs
tests/          one file per phase
```

## Honest limits

- Offline mode uses rule-based "models". It shows the mechanisms clearly, but the numbers it produces say nothing
  about model quality.
- The local adapters (SQLite checkpoints/store/audit, in-memory queue/bus) run in one process. The production
  adapters (SQS queue, Terraform) are included; wiring PostgresSaver, PostgresStore and Redis is the Phase 8 lab.
- The seed corpus is ~15 documents. The course target is 200+ pages: use `scripts/generate_corpus.py`, then
  write golden questions about the new docs.
- Dated facts in the course (EU AI Act timeline, MCP spec revision, model names and prices) reflect the course as written
  in Sept 2026. Verify them against primary sources before you rely on them.
