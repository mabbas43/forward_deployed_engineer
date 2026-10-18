# ATLAS — Governance (one page, for a security reviewer or DPO with 10 minutes)

**Purpose & scope.** ATLAS is an internal IT/HR/finance support assistant for Acme Logistics employees. It answers
questions from internal documents and, with human approval, performs a small set of account and finance actions.
It does not make decisions about employees.

**Data flows.** Ticket text → input guard (injection screen, PII pseudonymization) → LLM provider (EU endpoint) →
tools via MCP (IT directory, password reset) → resolution → output guard → employee. Logs, audit, memory and
checkpoints are held in the EU region (`eu-central-1`). Traces go to LangSmith EU.

**What is logged, where, and for how long** (`atlas/governance/policy.yaml → data.retention_days`)

| Store | Content | Identity | Retention |
|---|---|---|---|
| Audit (append-only) | every LLM/tool call, guard verdict, approval, route, promotion | `user_hash` (salted SHA-256) | 5 years |
| Checkpoints | ticket thread state incl. pseudonym map | thread owner hash | 90 days |
| Memory: cases | ticket, plan, outcome, rating | tenant-scoped, no raw PII | 365 days |
| Memory: prefs / procedures | language, channel / tenant rules | user hash / tenant | 180 days |
| Metrics | run records + online judge scores | trace id | 90 days |

**PII handling.** Detection uses deterministic recognizers (email, phone, IBAN with mod-97, Steuer-ID, credit card with
Luhn, medical terms); Presidio is an optional extra. **Input:** reversible pseudonymization, so the model sees
`<EMAIL_ADDRESS_1>` and tools receive the real value. **Output:** IBAN / national ID / card / medical content →
**blocked**, not redacted. The memory extractor refuses to store anything that contains PII.

**Model & data residency.** `models.eu_residency: true`. Non-EU endpoints are refused at startup
(`check_residency`). Terraform refuses non-`eu-*` regions. Only models listed in `models.allowed` may be used.

**Guardrail layers.** (0) prompt instructions, which are never sufficient on their own; (1) deterministic code:
token gate, PII, allow-lists, policy; (2) classifiers: injection score, with a hook for a Prompt-Guard-class model;
(3) LLM judge: grounding check on resolutions. Every verdict is an audited event and is monitored like an error rate.

**Approval gates & kill switch.** Every side-effecting tool has `requires_approval: true`, which pauses the graph as
a human interrupt. Policy is evaluated per step: role, quota, protected accounts, self-service limits, and
**taint**. A write is denied if the run's context contained flagged (possibly injected) content. Kill switches:
`kill_switch.tools`, `.agent`, `.routes`, hot-reloaded.

**Access & erasure.** `GET /users/{id}/export` (DPO role) returns audit rows, threads and prefs.
`DELETE /users/{id}` deletes the user's checkpoint threads and memory namespaces, pseudonymizes the user's audit
rows (keeps the row, erases identity and ticket text), and logs the erasure itself. Still needed in production:
LangSmith trace deletion/masking and an eval-dataset purge.

**EU AI Act posture** (as of Oct 2026; final classification is confirmed with Legal).
ATLAS is an internal support assistant that uses general-purpose AI models; Acme acts as a **deployer**. It is
**not high-risk by default**. Employment-related decisions fall under Annex III, so the **HR route never auto-acts**:
it summarizes and escalates to a human (`routes.hr.auto_act: false`). **Article 50:** every resolution carries an
AI disclosure ("ATLAS, an AI assistant…"). Deployer duties covered: human oversight (approval gates), logging
(audit), monitoring (online eval), transparency (notice), incident reporting (RUNBOOK RB-08), and an AI inventory
entry (below).

**AI inventory entry.** Name: ATLAS · Purpose: internal IT/HR/finance support · Models: gpt-4.1-mini / gpt-4.1 /
claude-sonnet-4-5 (EU endpoints) · Data: employee tickets, internal docs · Risk class: limited (Art. 50) ·
Owner: IT Platform · Review: quarterly.

**Incident response (summary).** Contain (kill switch) → assess with audit fields (`trace_id`, `tenant`,
`user_hash`, `route`, `tool`, `model`, `prompt_version`) → notify DPO within 24 h (GDPR Art. 33: authority within
72 h) → fix + regression case in `redteam_v1` → post-mortem.

**Evidence.** Red-team suite: `evals/datasets/redteam_v1.jsonl`, 60 cases, **100% handled as expected** (offline
run). Tests: `tests/test_p6_governance.py`. Threat model: `docs/THREAT_MODEL.md`.

Owner: IT Platform · Last review: 2026-10-11
