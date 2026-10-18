# Capstone acceptance (Phase 9) — evidence, not claims

Status legend: ✅ demonstrated in this repo (offline) · 🟡 implemented, needs your real-model / cloud run · ⬜ your work

| Criterion | Status | Evidence |
|---|---|---|
| 200+ pages ingested; recall@5 ≥ 0.85 & faithfulness ≥ 0.90 on a 50-question golden set | 🟡 | Pipeline + eval: `evals/rag_eval.py` (40 Q, recall@5 1.00 offline on the seed corpus). Grow the corpus with `scripts/generate_corpus.py` and the golden set to 50, then rerun with real embeddings |
| Three routes, data-driven table; one path needs approval and resumes after a restart | ✅ | `prompts/routes.v1.yaml`, `test_approval_survives_process_restart` |
| Two MCP servers, one remote with auth; allow-list, pinning, audit | ✅ | `atlas/mcp/`, `tests/test_p4_mcp.py`, `manifest.lock.json` |
| Memory-on vs memory-off curve over 60 tickets; namespace isolation in CI | ✅ (offline) / 🟡 real | `evals/adaptive_curve.py`: on 0.75 → 0.95, off 0.40 → 0.35; `test_namespaces_isolate_tenants_and_users` |
| Guardrails ≥ 95% on the 60-case red team; taint denial; erasure across stores; GOVERNANCE.md | ✅ | red team 100% offline; `test_poisoned_kb_doc_cannot_trigger_a_write`, `test_forget_user_empties_every_store`, `docs/GOVERNANCE.md` |
| Judges validated (TPR/TNR ≥ 0.85); CI gate blocks a bad PR; registry; online eval + drift alert; OTel | ✅ / 🟡 | `evals/validate_judges.py`, `.github/workflows/eval.yml`, `atlas/ops/registry.py`, `online_eval --demo`, `atlas/ops/telemetry.py` |
| Deployed to eu-central-1 via Terraform; load-tested at 200 concurrent; dashboard; failure-modes table | 🟡 | `infra/terraform` (validates), `load/locustfile.py`, `atlas/ops/dashboard.py`, `docs/ARCHITECTURE.md` |
| README with numbers; ARCHITECTURE / GOVERNANCE / RUNBOOK; 5-minute demo video | ✅ / ⬜ video | `README.md`, `docs/`; record `scripts/demo.py` + LangSmith trace + approval + dashboard |
