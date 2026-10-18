"""Tests run offline, without network or money, in an isolated data dir. Set env BEFORE importing atlas."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="atlas-test-")
os.environ["ATLAS_PROVIDER"] = "offline"
os.environ["DATA_DIR"] = _tmp

import pytest  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from atlas.agents.memory import memory_store  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def index():
    from atlas.rag.retrieve import get_retriever

    return get_retriever()  # builds the main index once per session


@pytest.fixture
def graph_factory():
    from atlas.agents.ticket_graph import GraphOptions, build

    def make(checkpointer=None, store=None, **opts):
        return build(checkpointer or InMemorySaver(), store if store is not None else memory_store(),
                     GraphOptions(**opts))

    return make


@pytest.fixture
def run_ticket(graph_factory):
    from atlas.agents.ticket_graph import config_for, new_ticket

    def run(text, role="it_support", user="anna.schmidt@acme-logistics.de", tenant="acme", graph=None, approve=None,
            ticket_id=None):
        g = graph or graph_factory()
        t = new_ticket(text, tenant=tenant, user_id=user, role=role, ticket_id=ticket_id)
        cfg = config_for(t["ticket_id"])
        out = g.invoke(t, cfg)
        if approve is not None and g.get_state(cfg).next == ("approval",):
            from langgraph.types import Command

            out = g.invoke(Command(resume="approve" if approve else "reject"), cfg)
        return out, g, cfg

    return run
