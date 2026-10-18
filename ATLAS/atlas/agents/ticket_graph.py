"""P3 + P5 + P6 — the ATLAS ticket graph: a workflow engine where some transitions are decided by an LLM.

    START → guard_input → route ─┬─ escalate ─────────────────────────────────────┐
                                 ├─ faq ──(answered)──────────────────────────────┤
                                 └─ triage ─┬─ hr → escalate                      │
                                            └─ retrieve → guard_retrieval → recall│
                                               → plan ⇄ reflect (≤2) ─┬─ approval ┤ (interrupt: human)
                                                                      ├─ execute ─┤
                                                                      └─ respond ─┤
                                         respond / escalate / faq → guard_output → finalize → END

The set of reachable transitions is fixed here, in code — the model only picks among them. That is a safety
property you can audit from this file alone. Every conditional edge lists its targets explicitly.

Durable execution: with a checkpointer, every step is saved under thread_id (= ticket_id). The approval
interrupt can wait for days and survive restarts; a node that crashed re-runs on resume — so every write
tool takes an idempotency key derived from (ticket_id, step).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from atlas.agents import memory as mem
from atlas.agents.plan import make_plan, write_resolution
from atlas.agents.reflect import MAX_ITER, critique
from atlas.agents.router import route as semantic_route
from atlas.agents.state import TicketState
from atlas.agents.steps import parse_step
from atlas.agents.tool_select import select
from atlas.agents.tools import TOOLS, WRITE_TOOLS
from atlas.governance.audit import audit, get_audit, user_hash
from atlas.governance.guards import AI_NOTICE, REFUSAL, UNAVAILABLE, check_input, check_output, scan_untrusted
from atlas.governance.pii import restore
from atlas.governance.policy import Ctx, evaluate_route, evaluate_tool, load_policy
from atlas.llm.client import triage
from atlas.logging import get_logger
from atlas.rag.generate import format_context
from atlas.rag.retrieve import get_retriever

log = get_logger()
MAX_STEPS = 6


class ToolsUnavailable(Exception):
    def __init__(self, server: str):
        super().__init__(server)
        self.server = server


@dataclass
class GraphOptions:
    routing: bool = True  # P5 semantic router
    memory: bool = True  # P5 episodic + procedural recall
    reflection: bool = True  # P5 bounded critique
    guards: bool = True  # P6 input / retrieval / output guards
    grounding: bool = True  # P6 LLM-judge grounding check on output
    tool_select_k: int = 0  # P5 tool RAG; 0 = bind all allowed tools
    tool_loader: Callable[[str], list] | None = None  # P4: MCP-loaded tools; default: local tools
    retrieval: str | None = None  # retrieval config name; None = prompts/active.yaml
    extra: dict = field(default_factory=dict)


def _ctx(s: TicketState) -> Ctx:
    return Ctx(tenant=s["tenant"], user_hash=user_hash(s.get("user_id", "anon")), role=s.get("user_role", "employee"),
               user_email=s.get("user_email", ""), trace_id=s.get("trace_id", ""))


def _accepts(tool, arg: str) -> bool:
    schema = tool.args_schema if isinstance(tool.args_schema, dict) else tool.args_schema.model_json_schema()
    return arg in schema.get("properties", {})


def _ev(name: str) -> dict:
    return {"events": [name]}


def build(checkpointer=None, store: BaseStore | None = None, options: GraphOptions | None = None):
    opt = options or GraphOptions()

    def tools_for(role: str) -> list:
        tools = opt.tool_loader(role) if opt.tool_loader else TOOLS
        policy = load_policy()  # least privilege: the model never sees tools its role can't use
        return [t for t in tools if role in policy["tools"].get(t.name, {}).get("roles", [])]

    # ---- guards (P6) --------------------------------------------------------------------------------
    def guard_input(s: TicketState) -> dict:
        policy = load_policy()
        ctx = _ctx(s)
        trace_id = s.get("trace_id") or f"{s['ticket_id']}:{uuid.uuid4().hex[:8]}"
        get_audit().register_thread(s["ticket_id"], s["tenant"], ctx.user_hash)
        audit("ticket_received", trace_id=trace_id, tenant=ctx.tenant, user_hash=ctx.user_hash, role=ctx.role,
              ticket_text=s["ticket_text"])
        base = {"trace_id": trace_id, "messages": [HumanMessage(s["ticket_text"])], **_ev("guard_input")}
        if policy["kill_switch"].get("agent"):
            return {**base, "blocked": True, "escalated": True, "resolution": UNAVAILABLE}
        if not opt.guards:
            return base
        v = check_input(s["ticket_text"], policy)
        audit("guardrail", trace_id=trace_id, tenant=ctx.tenant, user_hash=ctx.user_hash, check="input",
              blocked=v["blocked"], reason=v["reason"], score=v["score"])
        if v["blocked"]:
            return {**base, "blocked": True, "resolution": REFUSAL, "guard_notes": [v["reason"]]}
        return {**base, "ticket_text": v["text"], "pii_map": v["pii_map"]}

    def after_guard_input(s: TicketState) -> str:
        if s.get("blocked"):
            return "finalize"
        return "route" if opt.routing else "triage"

    def guard_retrieval(s: TicketState) -> dict:
        if not opt.guards:
            return _ev("guard_retrieval")
        clean, flagged = scan_untrusted(s.get("context", []), load_policy())
        for h in flagged:
            audit("guardrail", trace_id=s["trace_id"], tenant=s["tenant"], check="injection_indirect",
                  source=h["source"], blocked=True)
        return {"context": clean, "taint": bool(flagged) or s.get("taint", False), **_ev("guard_retrieval")}

    def guard_output(s: TicketState) -> dict:
        if not opt.guards:
            return _ev("guard_output")
        results = "\n".join(f"- {r['tool']}: {r['result']}" for r in s.get("tool_results", []))
        v = check_output(s.get("resolution", ""), format_context(s.get("context", [])), results, load_policy(),
                         grounding=opt.grounding and not s.get("escalated"))
        audit("guardrail", trace_id=s["trace_id"], tenant=s["tenant"], check="output",
              blocked_entities=v["blocked_entities"], grounded=v["grounded"])
        return {"resolution": v["text"], **_ev("guard_output")}

    # ---- routing (P5) -------------------------------------------------------------------------------
    def route_node(s: TicketState) -> dict:
        r = semantic_route(s["ticket_text"])
        audit("route", trace_id=s["trace_id"], tenant=s["tenant"], route=r["name"], score=r["score"])
        return {"route": r, **_ev("route")}

    def after_route(s: TicketState) -> str:
        return {"escalate": "escalate", "faq": "faq"}.get(s["route"]["name"], "triage")

    def faq_node(s: TicketState) -> dict:
        from atlas.rag.crag import build as build_crag

        out = build_crag().invoke({"question": s["ticket_text"], "tenant": s["tenant"],
                                   "role": s.get("user_role", "employee")})
        ans = out["answer"]
        if not ans["answerable"]:  # not in the docs → handle as a ticket
            return {"route": {**s["route"], "name": "ticket", "fallback_from": "faq"}, **_ev("faq")}
        return {"resolution": ans["answer"], "citations": ans["citations"], "context": out["hits"], **_ev("faq")}

    def after_faq(s: TicketState) -> str:
        return "guard_output" if s.get("resolution") else "triage"

    # ---- core (P3) ----------------------------------------------------------------------------------
    def triage_node(s: TicketState) -> dict:
        t = triage(s["ticket_text"], tags=[f"tenant:{s['tenant']}", f"ticket:{s['ticket_id']}"])
        audit("triage", trace_id=s["trace_id"], tenant=s["tenant"], category=t.category, urgency=t.urgency,
              needs_human=t.needs_human)
        return {"triage": t.model_dump(), **_ev("triage")}

    def after_triage(s: TicketState) -> str:
        cat = s["triage"]["category"]
        if not evaluate_route(load_policy(), cat).get("auto_act", True):
            return "escalate"  # HR never auto-acts (EU AI Act Annex III employment scope)
        return "retrieve"  # incl. "other": the docs may still answer it; respond escalates if nothing grounds it

    def retrieve_node(s: TicketState) -> dict:
        hits = get_retriever(opt.retrieval).retrieve(s["ticket_text"], s["tenant"], s.get("user_role", "employee"))
        return {"context": [h.as_dict() for h in hits], **_ev("retrieve")}

    def recall_node(s: TicketState, *, store: BaseStore | None = None) -> dict:
        if not (opt.memory and store is not None):
            return _ev("recall")
        good, avoid = mem.recall_cases(store, s["tenant"], s["ticket_text"])
        return {"recalled_cases": good, "avoid_cases": avoid,
                "procedures": mem.procedures(store, s["tenant"], s["ticket_text"]),
                "prefs": mem.prefs(store, s["tenant"], user_hash(s.get("user_id", "anon"))), **_ev("recall")}

    def plan_node(s: TicketState) -> dict:
        tools = tools_for(s.get("user_role", "employee"))
        if opt.tool_select_k:
            tools = select(s["ticket_text"], tools, opt.tool_select_k)
        p = make_plan(s, tools)
        return {"plan": p.steps[:MAX_STEPS], **_ev("plan")}

    def reflect_node(s: TicketState) -> dict:
        c = critique(s, tools_for(s.get("user_role", "employee")))
        audit("reflection", trace_id=s["trace_id"], tenant=s["tenant"], passes=c.passes, issues=c.issues,
              iteration=s.get("iterations", 0) + 1)
        return {"critique": c.model_dump(), "iterations": s.get("iterations", 0) + 1, **_ev("reflect")}

    def gate(s: TicketState) -> str:
        """After planning: writes needing approval → approval; any tool step → execute; else respond."""
        policy, ctx = load_policy(), _ctx(s)
        needs_approval = False
        has_tools = False
        for step in s.get("plan", []):
            kind, tool, args = parse_step(step)
            args = {k: restore(v, s.get("pii_map", {})) for k, v in args.items()}
            if tool:
                has_tools = True
            if kind == "CALL" or tool in WRITE_TOOLS:
                d = evaluate_tool(policy, tool or "", ctx, s, args)
                needs_approval |= d.allow and d.requires_approval
        if needs_approval:
            return "approval"
        return "execute" if has_tools else "respond"

    def after_reflect(s: TicketState) -> str:
        if s["critique"]["passes"] or s.get("iterations", 0) >= MAX_ITER:
            return gate(s)
        return "plan"

    def approval_node(s: TicketState) -> dict:
        policy, ctx = load_policy(), _ctx(s)
        writes = []
        for step in s["plan"]:
            kind, tool, args = parse_step(step)
            if kind == "CALL":
                d = evaluate_tool(policy, tool or "", ctx, s, {k: restore(v, s.get("pii_map", {})) for k, v in args.items()})
                writes.append({"step": step, "allowed": d.allow, "reason": d.reason})
        decision = interrupt({"ticket_id": s["ticket_id"], "tenant": s["tenant"], "plan": s["plan"],
                              "writes": writes, "triage": s.get("triage")})
        if isinstance(decision, dict):
            approved, approver = decision.get("decision") == "approve", decision.get("approver", "unknown")
        else:
            approved, approver = decision == "approve", "unknown"
        audit("approval", trace_id=s["trace_id"], tenant=s["tenant"], approved=approved, approver=approver,
              plan=s["plan"])
        return {"approved": approved, **_ev("approval")}

    def after_approval(s: TicketState) -> str:
        return "execute" if s["approved"] else "respond"

    def execute_node(s: TicketState) -> dict:
        policy, ctx = load_policy(), _ctx(s)
        try:
            by_name = {t.name: t for t in tools_for(ctx.role)}
        except ToolsUnavailable as e:
            return {"degraded": True, "escalated": True,
                    "resolution": f"IT systems are unavailable ({e.server}); this ticket is queued for a human.",
                    **_ev("execute")}
        results, taint = [], s.get("taint", False)
        for i, step in enumerate(s["plan"]):
            kind, tool, args = parse_step(step)
            if kind not in {"READ", "CALL"}:
                continue
            args = {k: restore(v, s.get("pii_map", {})) for k, v in args.items()}  # tools get real values
            quota = get_audit().count_today("tool_call", ctx.user_hash, tool or "")
            d = evaluate_tool(policy, tool or "", ctx, {**s, "taint": taint}, args, quota)
            if d.allow and d.requires_approval and not s.get("approved"):
                d.allow, d.reason = False, "not_approved"
            if kind == "READ" and tool in WRITE_TOOLS:
                d.allow, d.reason = False, "write_tool_in_read_step"
            if not d.allow or tool not in by_name:
                reason = d.reason if not d.allow else "tool_not_available"
                audit("policy", trace_id=s["trace_id"], tenant=ctx.tenant, user_hash=ctx.user_hash, tool=tool,
                      allow=False, reason=reason)
                results.append({"tool": tool, "args": args, "result": {"error": f"denied:{reason}"}})
                continue
            call_args = dict(args)
            if tool in WRITE_TOOLS:
                call_args["idempotency_key"] = f"{s['ticket_id']}:{i}"  # a resumed run never repeats a side effect
            call_args.pop("tenant", None)
            if _accepts(by_name[tool], "tenant"):
                call_args["tenant"] = ctx.tenant  # injected by code from the verified identity — never by the model
            try:
                res = by_name[tool].invoke(call_args)
            except Exception as e:  # infra failure → stop, escalate (don't let the model improvise)
                audit("tool_call", trace_id=s["trace_id"], tenant=ctx.tenant, user_hash=ctx.user_hash, tool=tool,
                      executed=False, error=type(e).__name__)
                results.append({"tool": tool, "args": args, "result": {"error": f"unavailable:{type(e).__name__}"}})
                return {"tool_results": results, "degraded": True, "escalated": True, **_ev("execute")}
            if opt.guards and scan_untrusted([{"text": str(res)}], policy)[1]:
                taint = True  # a tool result tried to inject instructions: block further writes this run
                audit("guardrail", trace_id=s["trace_id"], tenant=ctx.tenant, check="injection_tool_result", tool=tool)
            audit("tool_call", trace_id=s["trace_id"], tenant=ctx.tenant, user_hash=ctx.user_hash, tool=tool,
                  executed=True, ok="error" not in str(res))
            results.append({"tool": tool, "args": args, "result": res})
        return {"tool_results": results, "taint": taint, **_ev("execute")}

    def respond_node(s: TicketState) -> dict:
        if s.get("degraded") and s.get("resolution"):
            return _ev("respond")
        r = write_resolution(s)
        return {"resolution": r.text, "citations": r.citations, "escalated": r.escalated or s.get("escalated", False),
                **_ev("respond")}

    def escalate_node(s: TicketState) -> dict:
        reason = s.get("route", {}).get("name") if s.get("route", {}).get("name") == "escalate" else \
            (s.get("triage") or {}).get("category", "policy")
        audit("escalation", trace_id=s["trace_id"], tenant=s["tenant"], reason=reason)
        r = write_resolution({**s, "escalated": True})
        return {"resolution": r.text, "escalated": True, **_ev("escalate")}

    def finalize(s: TicketState) -> dict:
        text = s.get("resolution", "") + AI_NOTICE
        audit("resolution", trace_id=s.get("trace_id"), tenant=s["tenant"], escalated=bool(s.get("escalated")),
              blocked=bool(s.get("blocked")), route=(s.get("route") or {}).get("name"))
        return {"resolution": text, "messages": [AIMessage(text)], **_ev("finalize")}

    g = StateGraph(TicketState)
    nodes = {
        "guard_input": guard_input, "route": route_node, "faq": faq_node, "triage": triage_node,
        "retrieve": retrieve_node, "guard_retrieval": guard_retrieval, "recall": recall_node, "plan": plan_node,
        "reflect": reflect_node, "approval": approval_node, "execute": execute_node, "respond": respond_node,
        "escalate": escalate_node, "guard_output": guard_output, "finalize": finalize,
    }
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "guard_input")
    g.add_conditional_edges("guard_input", after_guard_input, ["route", "triage", "finalize"])
    g.add_conditional_edges("route", after_route, ["escalate", "faq", "triage"])
    g.add_conditional_edges("faq", after_faq, ["guard_output", "triage"])
    g.add_conditional_edges("triage", after_triage, ["escalate", "retrieve"])
    g.add_edge("retrieve", "guard_retrieval")
    g.add_edge("guard_retrieval", "recall")
    g.add_edge("recall", "plan")
    if opt.reflection:
        g.add_edge("plan", "reflect")
        g.add_conditional_edges("reflect", after_reflect, ["plan", "approval", "execute", "respond"])
    else:
        g.add_conditional_edges("plan", gate, ["approval", "execute", "respond"])
    g.add_conditional_edges("approval", after_approval, ["execute", "respond"])
    g.add_edge("execute", "respond")
    g.add_edge("respond", "guard_output")
    g.add_edge("escalate", "guard_output")
    g.add_edge("guard_output", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


def new_ticket(text: str, *, tenant: str = "acme", user_id: str = "anna.schmidt@acme-logistics.de",
               role: str = "it_support", ticket_id: str | None = None) -> dict:
    return {"ticket_id": ticket_id or f"t-{uuid.uuid4().hex[:8]}", "ticket_text": text, "tenant": tenant,
            "user_id": user_id, "user_email": user_id, "user_role": role}


def config_for(ticket_id: str, **extra) -> RunnableConfig:
    """thread_id = ticket_id: a ticket is the unit of work and approval (not the user — users have many)."""
    return {"configurable": {"thread_id": ticket_id}, "recursion_limit": 40, **extra}


def dev_checkpointer():
    """Persistent local checkpointer (SQLite). Tests: InMemorySaver. Production: PostgresSaver."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    from atlas.config import settings

    return SqliteSaver(sqlite3.connect(settings.data_dir / "checkpoints.sqlite", check_same_thread=False))


def graph_for_studio():
    """Entry point for `langgraph dev` (see langgraph.json). Studio supplies its own persistence."""
    return build(store=None)
