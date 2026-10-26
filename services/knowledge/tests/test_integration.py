"""Live integration checks; run with the repository dev Postgres and Qdrant."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from _dbenv import test_database_url
from qdrant_client import QdrantClient
from sqlalchemy import delete, select

from aihub_knowledge.acl import Principal
from aihub_knowledge.db import ChunkRow, DocumentRow, make_engine, session_factory
from aihub_knowledge.embeddings import FakeEmbeddingBackend
from aihub_knowledge.qdrant_store import QdrantStore
from aihub_knowledge.reconcile import PersistentIndex
from aihub_knowledge.search_service import HybridSearcher

pytestmark = pytest.mark.integration


@pytest.fixture
def live_index(tmp_path: Path):
    engine = make_engine(test_database_url())
    client = QdrantClient(url=os.environ.get("AIHUB_QDRANT_URL", "http://127.0.0.1:56333"), check_compatibility=False)
    store = QdrantStore(client, "knowledge_fake_integration")
    if client.collection_exists(store.collection):
        client.delete_collection(store.collection)
    root = tmp_path / "vault"
    root.mkdir()
    settings = SimpleNamespace(chunk_size=1200, chunk_overlap=150)
    index = PersistentIndex(engine, store, FakeEmbeddingBackend("fake", "integration"), settings)
    yield root, index, store, engine
    with session_factory(engine)() as session:
        session.execute(delete(ChunkRow).where(ChunkRow.doc_id.in_(["it-a", "it-b", "it-private", "vault:plain.md"])))
        session.execute(delete(DocumentRow).where(DocumentRow.id.in_(["it-a", "it-b", "it-private", "vault:plain.md"])))
        session.commit()
    if client.collection_exists(store.collection):
        client.delete_collection(store.collection)
    engine.dispose()


def _write(root: Path, name: str, doc_id: str, project: str, body: str, visibility: str = "private"):
    (root / name).write_text(
        f"""---
id: {doc_id}
project_id: {project}
type: overview
title: {doc_id}
updated_at: 2026-10-23T00:00:00Z
source: human
status: active
visibility: {visibility}
schema_version: 1
---
# Notes
{body}
""",
        encoding="utf-8",
    )


def test_live_reconcile_acl_delete_and_rename(live_index):
    root, index, store, engine = live_index
    _write(root, "a.md", "it-a", "alpha", "old unique phrase")
    _write(root, "b.md", "it-b", "beta", "private beta phrase")
    index.reconcile(root)
    search = HybridSearcher(engine, store, index.embedder)
    assert any(
        hit["doc_id"] == "it-a"
        for hit in search.search("old unique phrase", Principal("u", "viewer", frozenset({"alpha"})))
    )
    assert not any(
        hit["doc_id"] == "it-b"
        for hit in search.search("private beta phrase", Principal("u", "viewer", frozenset({"alpha"})))
    )
    (root / "a.md").write_text((root / "a.md").read_text().replace("old unique phrase", "new unique phrase"))
    index.reconcile(root)
    with session_factory(engine)() as session:
        assert not session.scalars(select(ChunkRow).where(ChunkRow.content.contains("old unique phrase"))).all()
    (root / "a.md").rename(root / "renamed.md")
    index.reconcile(root)
    with session_factory(engine)() as session:
        doc = session.get(DocumentRow, "it-a")
        assert doc.path == "renamed.md"
    (root / "renamed.md").unlink()
    index.reconcile(root)
    assert store.client.count(store.collection).count == 1


def test_live_chunk_ids_and_migration_acl_boundary(live_index):
    root, index, _store, engine = live_index
    _write(root, "a.md", "it-a", "alpha", "section one\n# Other\nsection two")
    index.reconcile(root)
    with session_factory(engine)() as session:
        before = {c.heading: c.id for c in session.scalars(select(ChunkRow).where(ChunkRow.doc_id == "it-a"))}
    (root / "a.md").write_text((root / "a.md").read_text().replace("section two", "changed section two"))
    index.reconcile(root)
    with session_factory(engine)() as session:
        after = {c.heading: c.id for c in session.scalars(select(ChunkRow).where(ChunkRow.doc_id == "it-a"))}
    assert before["Notes"] == after["Notes"]


def test_live_plain_note_is_admin_only(live_index):
    root, index, store, engine = live_index
    (root / "plain.md").write_text("# Private homelab note\nunique private homelab phrase", encoding="utf-8")
    index.reconcile(root)
    search = HybridSearcher(engine, store, index.embedder)

    assert any(
        hit["doc_id"] == "vault:plain.md"
        for hit in search.search("unique private homelab phrase", Principal("admin", "admin", frozenset()))
    )
    assert not any(
        hit["doc_id"] == "vault:plain.md"
        for hit in search.search("unique private homelab phrase", Principal("viewer", "viewer", frozenset()))
    )


def test_live_vector_result_and_postgres_acl_recheck(live_index):
    root, index, store, engine = live_index
    _write(root, "a.md", "it-a", "alpha", "vector-only phrase")
    index.reconcile(root)
    search = HybridSearcher(engine, store, index.embedder)
    hits = search.search("vector-only phrase", Principal("u", "viewer", frozenset({"alpha"})))
    assert any(hit["match"] in {"vector", "hybrid"} for hit in hits)

    with session_factory(engine)() as session:
        doc = DocumentRow(
            id="it-private",
            project_id="beta",
            path="private.md",
            title="private",
            visibility="private",
            content="not in lexical text",
            content_hash="b" * 64,
            updated_at=datetime.now(UTC),
        )
        session.add(doc)
        session.add(
            ChunkRow(
                id="00000000-0000-0000-0000-000000000001",
                doc_id="it-private",
                heading="Private",
                heading_path="Private",
                content="private vector-only phrase",
                content_hash="c" * 64,
                line_start=1,
                line_end=1,
                embedding_model="fake",
                embedding_version="integration",
            )
        )
        session.commit()
    vector = index.embedder.embed(["private vector-only phrase"])[0]
    store.ensure_collection(len(vector))
    store.upsert(
        [
            (
                "00000000-0000-0000-0000-000000000001",
                vector,
                {
                    "project_id": "beta",
                    "visibility": "private",
                    "doc_id": "it-private",
                    "chunk_id": "00000000-0000-0000-0000-000000000001",
                },
            )
        ]
    )
    assert not any(
        hit["doc_id"] == "it-private"
        for hit in search.search("private vector-only phrase", Principal("u", "viewer", frozenset({"alpha"})))
    )


def test_live_vector_only_hits_need_the_relevance_threshold(live_index):
    root, index, store, engine = live_index
    _write(root, "a.md", "it-a", "alpha", "the quick brown fox")
    index.reconcile(root)
    admin = Principal("admin", "admin", frozenset())
    # No word overlap: only nearest neighbours, which an unreachable threshold must drop.
    assert HybridSearcher(engine, store, index.embedder, vector_only_min_score=2.0).search("zzzz qqqq", admin) == []
    assert HybridSearcher(engine, store, index.embedder, vector_only_min_score=-1.0).search("zzzz qqqq", admin)
    # Lexical matches are kept whatever the threshold.
    assert HybridSearcher(engine, store, index.embedder, vector_only_min_score=2.0).search("quick brown fox", admin)
