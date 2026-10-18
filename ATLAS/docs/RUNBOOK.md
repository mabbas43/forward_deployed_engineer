# ATLAS — Runbook

Each alert links here. First steps are concrete. Use the audit fields: `trace_id`, `tenant`, `user_hash`, `route`,
`tool`, `model`, `prompt_version`.

## RB-01 Provider 429 storm / outage
1. `GET /healthz`: is the breaker `open`? Check the provider status page.
2. Logs: `llm_call` events. Is `model` switching to the backup (fallback firing)? Is `latency_ms` rising?
3. If both providers are degraded, set `kill_switch.tools: true` (reads keep working) or `.agent: true` (all tickets queued for humans).
4. After recovery: the breaker half-opens by itself. Confirm queue depth drains.

## RB-02 Worker crash mid-graph
1. Redelivered messages appear after the visibility timeout (360 s). Any worker resumes from the checkpoint.
2. Verify no duplicate side effects: `write_ledger` and backend dedupe by `(ticket_id, step)`.
3. Messages in the DLQ after 3 receives need a human: inspect the state with `graph.get_state(config_for(ticket_id))`.

## RB-03 Queue depth spike
1. Which tenant lane? A bulk submission is fine (round-robin protects others). Check other tenants' p95.
2. Scale workers (they autoscale on backlog). If the provider TPM is the bottleneck, raise limits or shed load (API 429).

## RB-04 Stale cache answer
1. Confirm the cache key contains prompt + retrieval version (`atlas/api/cache.py: version_key`).
2. Flush the tenant's semantic cache; tighten the threshold; review audited `cache_hit` events.

## RB-05 MCP server down
1. Tickets degrade to "IT systems are unavailable; queued for a human". Check the `mcp-it` health/logs.
2. Token expired? Confirm `401 token_expired` and IdP health.

## RB-06 Database failover
Aurora fails over automatically. Workers retry, and unacked tickets redeliver and resume from checkpoints.

## RB-07 Quality alert ("grounded dropped ≥ 3 points") — the 03:00 page
1. Provider status + **fingerprint change** in `llm_call` logs (provider drift?).
2. Last promotion: `uv run python -m atlas.ops.registry show` → `history`.
3. Run the gate on the active config: `uv run python -m evals.run`.
4. If the regression came from our change: `uv run python -m atlas.ops.registry rollback prompts.<name>`.
5. Sample 20 failing traces (`scores` where key=grounded and score=0) → add them to `golden_v1` → open an incident with trace links.

## RB-08 PII leak
1. Kill switch for the affected route. Pull the audit rows by `trace_id`.
2. Notify the DPO within 24 h (dpo@acme-logistics.de). The authority must be notified within 72 h (GDPR Art. 33).
3. Add the case to `redteam_v1`, fix the recognizer/guard, and make the gate pass before re-enabling.

## RB-09 Escalation rate doubled
1. Router change? Triage prompt change? Check `history` in `active.yaml`.
2. Look at the `route` audit events: has the score distribution shifted? (user drift → new exemplars needed)

## RB-10 Canary worse than stable
1. Set `canary_weight=0` (Terraform var) → apply.
2. `registry rollback` if the change was already promoted. Attach the shadow report to the post-mortem.
