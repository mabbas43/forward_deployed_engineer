"""An offline, deterministic stand-in for a chat model.

Why it exists: so you can run every phase, test, eval and drill without API keys or spend. It is a real
`BaseChatModel`, so callbacks (CostTracker), tracing, `with_structured_output`, `.batch()` and
`.with_fallbacks()` all behave exactly as with a provider — only the "intelligence" is rule-based.

Each structured schema registers a heuristic handler next to where the schema is defined:

    @offline.handles(TicketTriage)
    def _triage(task: offline.Task) -> dict: ...

Never mistake offline numbers for model quality. Use them to learn the *machinery*; rerun with keys for real numbers.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

MODEL_NAME = "offline-heuristic"


@dataclass
class Task:
    system: str
    human: str
    messages: list[BaseMessage]

    @property
    def text(self) -> str:
        return f"{self.system}\n{self.human}"

    def section(self, name: str) -> str:
        """Extract `<name>...</name>` blocks that ATLAS prompts use to delimit inputs."""
        for src in (self.human, self.system):  # inputs live in the human turn; system prompts only *mention* tags
            m = re.search(rf"<{name}>\n(.*?)\n</{name}>", src, re.S) or re.search(rf"<{name}>(.*?)</{name}>", src, re.S)
            if m:
                return m.group(1).strip()
        return ""


_HANDLERS: dict[str, Callable[[Task], dict]] = {}

# Modules that define structured schemas + their offline handlers. Imported lazily on first call.
HANDLER_MODULES = [
    "atlas.llm.client",
    "atlas.rag.rewrite",
    "atlas.rag.generate",
    "atlas.rag.crag",
    "atlas.agents.plan",
    "atlas.agents.reflect",
    "atlas.agents.extract",
    "atlas.agents.supervisor",
    "atlas.governance.judges",
    "evals.judges",
]
_loaded = False


def _ensure_loaded():
    global _loaded
    if _loaded:
        return
    import importlib

    for mod in HANDLER_MODULES:
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if e.name != mod:  # a real missing dependency inside the module — surface it
                raise
    _loaded = True


def _key(schema: Any) -> str:
    return f"{schema.__module__}.{schema.__qualname__}"


def handles(schema: Any):
    def deco(fn: Callable[[Task], dict]):
        _HANDLERS[_key(schema)] = fn
        return fn

    return deco


def _approx_tokens(s: str) -> int:
    return max(1, len(s) // 4)


class OfflineChatModel(BaseChatModel):
    schema_key: str | None = None

    @property
    def _llm_type(self) -> str:
        return MODEL_NAME

    @property
    def _identifying_params(self) -> dict:
        return {"model_name": MODEL_NAME}

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kw) -> ChatResult:
        system = "\n".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
        human = "\n".join(str(m.content) for m in messages if isinstance(m, HumanMessage))
        task = Task(system=system, human=human, messages=messages)
        if self.schema_key:
            if self.schema_key not in _HANDLERS:
                _ensure_loaded()
            handler = _HANDLERS.get(self.schema_key)
            if handler is None:
                raise NotImplementedError(f"No offline handler registered for {self.schema_key}")
            content = json.dumps(handler(task))
        else:
            content = human[-500:]  # plain-text calls just echo; ATLAS uses structured output everywhere
        ti, to = _approx_tokens(system + human), _approx_tokens(content)
        msg = AIMessage(
            content=content,
            usage_metadata={"input_tokens": ti, "output_tokens": to, "total_tokens": ti + to},
            response_metadata={"model_name": MODEL_NAME, "system_fingerprint": "offline-v1"},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def with_structured_output(self, schema, **kw):  # type: ignore[override]
        model = self.model_copy(update={"schema_key": _key(schema)})
        return model | RunnableLambda(lambda m: schema.model_validate_json(m.content), name="parse")


# ---- tiny text helpers shared by heuristic handlers -------------------------------------------------

WORD = re.compile(r"[a-zA-ZäöüÄÖÜß0-9][\w\-äöüÄÖÜß]*")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def words(s: str) -> set[str]:
    return {w.lower() for w in WORD.findall(s)}


def has_any(s: str, terms: list[str]) -> bool:
    low = s.lower()
    return any(t in low for t in terms)


def first_email(s: str) -> str | None:
    m = EMAIL.search(s)
    return m.group(0) if m else None
