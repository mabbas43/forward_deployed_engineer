"""ATLAS — an adaptive operations copilot.

Layers (see docs/ARCHITECTURE.md):
  llm/        P1  model access: clients, structured output, cost, budget, token gate
  rag/        P2  knowledge: ingest, hybrid retrieval, rerank, rewrite, corrective RAG
  agents/     P3+P5 orchestration + adaptation: graphs, memory, reflection, routing
  mcp/        P4  integration: MCP servers + governed client
  governance/ P6  control: guardrails, policy-as-code, audit, erasure
  ops/        P7  operations: registry, online eval, telemetry, rollout
  api/        P8  platform: FastAPI, queue, worker, resilience
"""

__version__ = "0.9.0"
