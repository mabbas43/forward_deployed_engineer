"""P2 — ingestion is a data pipeline, not a script: load → clean → split → enrich → embed → upsert.

Three properties make it production-grade:
- idempotent:  content-hash IDs; re-running never duplicates
- incremental: a manifest of (path, sha); unchanged files skip, changed files re-index, deleted files purge
- observable:  counts per stage, per run

Chunking = parent–child: small children (~450 chars) are matched; the parent section is what the model reads.
Tables stay whole (a split table answers nothing) and get a one-line summary so they're findable.

    uv run python scripts/ingest.py            # all tenants under data/corpus/
"""

import hashlib
import re
from pathlib import Path

import yaml
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from atlas.config import settings
from atlas.logging import get_logger
from atlas.rag.embeddings import get_embeddings
from atlas.rag.stores import Index

log = get_logger()

HEADERS = MarkdownHeaderTextSplitter([("#", "h1"), ("##", "h2"), ("###", "h3")], strip_headers=False)
CHILD = RecursiveCharacterTextSplitter(chunk_size=450, chunk_overlap=60)
TABLE_RE = re.compile(r"(?m)((?:^\|.*\|[ \t]*\n?){2,})")


def cid(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:20]


def parse_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body.strip()
    return {}, text


def split_keeping_tables(text: str) -> list[str]:
    """Return prose pieces and whole tables. Tables are never cut by the character splitter."""
    pieces, last = [], 0
    for m in TABLE_RE.finditer(text):
        if m.start() > last:
            pieces.append(text[last : m.start()])
        pieces.append(m.group(1))
        last = m.end()
    pieces.append(text[last:])
    return [p.strip() for p in pieces if p.strip()]


def table_summary(table: str) -> str:
    """Deterministic table summary: header row + first column. (Level 2: an LLM-written one-liner.)"""
    rows = [r for r in table.strip().splitlines() if r.strip() and not set(r.strip()) <= set("|-: ")]
    header = rows[0].strip("|").replace("|", ",") if rows else ""
    keys = ", ".join(r.strip("|").split("|")[0].strip() for r in rows[1:])
    return f"Table with columns {header.strip()}; rows: {keys}."


def contextualize(doc_title: str, section: str, chunk: str) -> str:
    """Anthropic-style contextual prefix. Offline: deterministic from title + section; online: prompts/context.v1."""
    if settings.online:
        from pydantic import BaseModel

        from atlas.llm.prompts import load
        from atlas.llm.providers import structured

        class Situated(BaseModel):
            sentence: str

        system, _ = load("context")
        out = structured(Situated, "cheap").invoke(
            [("system", system), ("human", f"<document>\n{doc_title} / {section}\n</document>\n<chunk>\n{chunk}\n</chunk>")])
        return out.sentence
    return f"From '{doc_title}', section '{section}'."


def ingest_file(path: Path, tenant: str, rel: str, index: Index, *, contextual: bool = False) -> dict:
    raw = path.read_text()
    sha = cid(raw)
    if index.manifest.get(rel + "@" + tenant) == sha:
        return {"skipped": 1}
    removed = index.vectors.purge(f"{tenant}/{rel}")  # changed file: drop old children first
    for pid, p in list(index.parents.items()):
        if p["source"] == f"{tenant}/{rel}":
            index.parents.pop(pid)

    meta, body = parse_front_matter(raw)
    title = meta.get("title", path.stem)
    base = {
        "tenant": tenant,
        "source": f"{tenant}/{rel}",
        "title": title,
        "access_level": meta.get("access_level", "employee"),
        "effective_from": str(meta.get("effective_from", "")),
        "status": meta.get("status", "current"),
    }
    stats = {"parents": 0, "children": 0, "removed": removed}
    texts, metas, ids = [], [], []
    for parent in HEADERS.split_text(body):
        section = parent.metadata.get("h3") or parent.metadata.get("h2") or parent.metadata.get("h1") or title
        if parent.page_content.strip().startswith("#") and len(parent.page_content.strip().splitlines()) == 1:
            continue  # a bare title line is not a section
        pid = cid(parent.page_content + base["source"])
        key = f"{rel}#{section}"
        index.parents.put(pid, {"text": parent.page_content, "key": key, "section": section, **base})
        stats["parents"] += 1
        for piece in split_keeping_tables(parent.page_content):
            is_table = piece.lstrip().startswith("|")
            chunks = [piece] if is_table else CHILD.split_text(piece)
            for c in chunks:
                body_text = f"{table_summary(c)}\n{c}" if is_table else c
                if contextual:
                    body_text = f"{contextualize(title, section, c)}\n{body_text}"
                else:
                    body_text = f"{title} — {section}\n{body_text}"  # cheap structural context
                texts.append(body_text)
                ids.append(cid(body_text + pid))
                metas.append({**base, "parent_id": pid, "key": key, "section": section, "is_table": is_table})
    if texts:
        vecs = get_embeddings().embed_documents(texts)
        for id_, t, m, v in zip(ids, texts, metas, vecs, strict=True):
            stats["children"] += int(index.vectors.add(id_, t, m, v))
    index.manifest.put(rel + "@" + tenant, sha)
    return stats


def ingest_corpus(corpus: Path | None = None, index_name: str = "main", *, contextual: bool = False,
                  extra: list[tuple[Path, str]] | None = None) -> dict:
    """Ingest data/corpus/<tenant>/**.md. `extra` = [(path, tenant)] for drills (e.g. the poisoned doc)."""
    corpus = corpus or settings.corpus_dir
    index = Index(index_name)
    totals = {"files": 0, "skipped": 0, "parents": 0, "children": 0, "removed": 0, "purged_files": 0}
    seen = set()
    jobs: list[tuple[Path, str, str]] = []
    for tdir in sorted(p for p in corpus.iterdir() if p.is_dir()):
        for f in sorted(tdir.rglob("*.md")):
            jobs.append((f, tdir.name, str(f.relative_to(tdir))))
    for f, tenant in extra or []:
        jobs.append((f, tenant, f"extra/{f.name}"))
    for f, tenant, rel in jobs:
        seen.add(rel + "@" + tenant)
        s = ingest_file(f, tenant, rel, index, contextual=contextual)
        totals["files"] += 1
        for k, v in s.items():
            totals[k] = totals.get(k, 0) + v
    for key in [k for k, _ in index.manifest.items() if k not in seen]:  # deleted files → purge
        rel, tenant = key.rsplit("@", 1)
        index.vectors.purge(f"{tenant}/{rel}")
        for pid, p in list(index.parents.items()):
            if p["source"] == f"{tenant}/{rel}":
                index.parents.pop(pid)
        index.manifest.pop(key)
        totals["purged_files"] += 1
    index.save()
    log.info("ingest_done", index=index_name, vectors=len(index.vectors), **totals)
    return {**totals, "vectors": len(index.vectors)}
