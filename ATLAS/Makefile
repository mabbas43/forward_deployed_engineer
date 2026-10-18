# ATLAS — common commands. Everything runs offline unless keys are set in .env.
.PHONY: setup test lint ingest ragEval gate judges curve demo api mcp-it online dash lock compose-up load

setup:      ; uv sync && cp -n .env.example .env || true
test:       ; uv run pytest
lint:       ; uv run ruff check . && uv run python scripts/lock_manifest.py --check
ingest:     ; uv run python scripts/ingest.py
ragEval:    ; uv run python -m evals.rag_eval
gate:       ; uv run python -m evals.run
judges:     ; uv run python -m evals.validate_judges
curve:      ; uv run python -m evals.adaptive_curve
demo:       ; uv run python scripts/demo.py
api:        ; uv run uvicorn atlas.api.main:app --reload --port 8000
mcp-it:     ; uv run python -m atlas.mcp.it_server
online:     ; uv run python -m atlas.ops.online_eval --once
dash:       ; uv run python -m atlas.ops.dashboard
lock:       ; uv run python scripts/lock_manifest.py
studio:     ; uvx --from "langgraph-cli[inmem]" langgraph dev
compose-up: ; docker compose -f infra/docker-compose.yml up --build
load:       ; uv run --extra load locust -f load/locustfile.py --host http://localhost:8000
