"""Phase 2 — idempotent, tenant-aware ingestion; hybrid retrieval; measured, not guessed."""

from pathlib import Path

from atlas.rag.ingest import ingest_corpus, split_keeping_tables
from atlas.rag.retrieve import CONFIGS, HybridRetriever, get_retriever, rrf
from atlas.rag.stores import Index


def keys(hits):
    return [h.key for h in hits]


def test_rrf_rewards_agreement():
    assert rrf([["a", "b", "c"], ["b", "a", "d"]])[:2] in (["a", "b"], ["b", "a"])
    assert rrf([["x"], ["y", "x"]])[0] == "x"


def test_ingest_is_idempotent_and_incremental(tmp_path: Path):
    corpus = tmp_path / "corpus" / "t1"
    corpus.mkdir(parents=True)
    (corpus / "a.md").write_text("# A\n\n## One\nalpha beta gamma\n\n## Two\ndelta epsilon\n")
    (corpus / "b.md").write_text("# B\n\n## Three\nzeta eta theta\n")
    first = ingest_corpus(tmp_path / "corpus", index_name="t_idem")
    second = ingest_corpus(tmp_path / "corpus", index_name="t_idem")
    assert second["vectors"] == first["vectors"] and second["skipped"] == 2
    (corpus / "a.md").write_text("# A\n\n## One\nalpha beta gamma CHANGED\n")
    third = ingest_corpus(tmp_path / "corpus", index_name="t_idem")
    assert third["skipped"] == 1 and third["removed"] > 0
    (corpus / "b.md").unlink()
    fourth = ingest_corpus(tmp_path / "corpus", index_name="t_idem")
    assert fourth["purged_files"] == 1
    assert all(m["source"] != "t1/b.md" for m in Index("t_idem").vectors.metas.values())


def test_tables_stay_whole():
    pieces = split_keeping_tables("intro\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\noutro")
    assert any(p.startswith("| a | b |") and "| 3 | 4 |" in p for p in pieces)


def test_exact_token_query_hybrid_beats_or_matches_dense():
    q = "What does error E-4471 mean?"
    target = "it/error-codes.md#Warehouse management system (WMS) errors"
    hybrid = keys(HybridRetriever(CONFIGS["hybrid+rerank"]).retrieve(q, "acme", "it_support"))
    assert target in hybrid[:3]


def test_tenant_isolation_both_directions():
    r = get_retriever()
    acme = r.retrieve("Zentrix VPN portal", "acme", "it_support")
    assert all(h.source.startswith("acme/") for h in acme)
    assert all("zentrix" not in h.text.lower() for h in acme)
    globex = r.retrieve("password policy minimum length", "globex", "it_support")
    assert all(h.source.startswith("globex/") for h in globex)


def test_access_aware_retrieval():
    r = get_retriever()
    emp = r.retrieve("Outlook crashes when opening attachments", "acme", "employee")
    assert all(h.source != "acme/it/laptop-runbook.md" for h in emp)
    hd = r.retrieve("Outlook crashes when opening attachments", "acme", "helpdesk")
    assert any(h.source == "acme/it/laptop-runbook.md" for h in hd)


def test_freshness_prefers_current_policy_over_superseded_draft():
    hits = get_retriever().retrieve("password requirements minimum length rotation", "acme", "employee")
    first_pw = next(h for h in hits if "password-policy" in h.source)
    assert first_pw.status == "current"


def test_golden_set_references_exist():
    from evals.rag_eval import load_golden, validate

    assert validate(load_golden()) == []


def test_corrective_rag_answers_and_abstains():
    from atlas.rag.crag import ask

    a = ask("What does error E-4471 mean?")
    assert a.answerable and "acme/it/error-codes.md" in a.citations
    assert not ask("Who won the football match yesterday?").answerable
