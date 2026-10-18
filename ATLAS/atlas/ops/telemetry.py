"""P7 — OpenTelemetry GenAI semantic conventions, alongside LangSmith.

Emitting `gen_ai.*` attributes means a Python agent, a raw SDK call and a Java service line up in one waterfall,
and you can swap observability backends. The conventions are still marked *Development* — names may move.
Telemetry must NEVER block serving: every export path swallows its own errors.

    uv sync --extra otel
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 uv run python scripts/run_ticket.py "VPN drops"
"""

import os
import time

from langchain_core.callbacks import BaseCallbackHandler

from atlas.logging import get_logger

log = get_logger()

try:
    from opentelemetry import trace

    _tracer = trace.get_tracer("atlas")
except ImportError:  # optional extra
    _tracer = None


def setup_tracing(service: str = "atlas") -> bool:
    """Configure an OTLP exporter if the SDK is installed and an endpoint is set. Returns True if active."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
        trace.set_tracer_provider(provider)
        global _tracer
        _tracer = trace.get_tracer("atlas")
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("otel_setup_failed", err=repr(e))
        return False


class OTelGenAICallback(BaseCallbackHandler):
    """One span per LLM call (`chat <model>`) and per tool call (`execute_tool <name>`)."""

    def __init__(self):
        self._spans: dict = {}

    def _start(self, run_id, name: str, attrs: dict):
        if _tracer is None:
            return
        try:
            span = _tracer.start_span(name)
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(k, v)
            self._spans[run_id] = (span, time.perf_counter())
        except Exception:  # noqa: BLE001
            pass

    def _end(self, run_id, attrs: dict):
        item = self._spans.pop(run_id, None)
        if not item:
            return
        try:
            span, _ = item
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(k, v)
            span.end()
        except Exception:  # noqa: BLE001
            pass

    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        p = kw.get("invocation_params") or {}
        model = p.get("model") or p.get("model_name") or "unknown"
        self._start(run_id, f"chat {model}", {"gen_ai.operation.name": "chat", "gen_ai.request.model": model,
                                              "gen_ai.request.temperature": p.get("temperature")})

    def on_llm_end(self, response, *, run_id, **kw):
        msg = getattr(response.generations[0][0], "message", None)
        um = getattr(msg, "usage_metadata", None) or {}
        meta = getattr(msg, "response_metadata", {}) or {}
        self._end(run_id, {"gen_ai.usage.input_tokens": um.get("input_tokens"),
                           "gen_ai.usage.output_tokens": um.get("output_tokens"),
                           "gen_ai.response.model": meta.get("model_name")})

    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        name = (serialized or {}).get("name", "tool")
        self._start(run_id, f"execute_tool {name}", {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name})

    def on_tool_end(self, output, *, run_id, **kw):
        self._end(run_id, {})

    def on_llm_error(self, error, *, run_id, **kw):
        self._end(run_id, {"error.type": type(error).__name__})

    on_tool_error = on_llm_error
