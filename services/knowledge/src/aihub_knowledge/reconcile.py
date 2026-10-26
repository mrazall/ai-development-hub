from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from .chunking import chunk_document
from .db import ChunkRow, DocumentLinkRow, DocumentRow, IndexErrorRow, session_factory
from .embeddings import EmbeddingBackend
from .graph import extract_links, resolve_link
from .qdrant_store import QdrantStore
from .vault import KnowledgeDocument, VaultError, scan_vault


@dataclass
class InMemoryIndex:
    """Compatibility fixture for unit tests; production uses PersistentIndex."""

    documents: dict[str, KnowledgeDocument] = field(default_factory=dict)
    chunks: dict[str, object] = field(default_factory=dict)
    errors: list[VaultError] = field(default_factory=list)

    def reconcile(self, root: Path, embedder: EmbeddingBackend, chunk_size: int = 1200, overlap: int = 150) -> None:
        documents, errors = scan_vault(root)
        current = {d.id: d for d in documents}
        for doc_id in set(self.documents) - set(current):
            self.documents.pop(doc_id, None)
            self.chunks = {k: v for k, v in self.chunks.items() if getattr(v, "doc_id", None) != doc_id}
        for document in documents:
            if self.documents.get(document.id) and self.documents[document.id].content_hash == document.content_hash:
                continue
            self.chunks = {k: v for k, v in self.chunks.items() if getattr(v, "doc_id", None) != document.id}
            self.chunks.update({c.id: c for c in chunk_document(document, chunk_size, overlap)})
            self.documents[document.id] = document
        self.errors = errors

    def search(self, query: str, allowed_project_ids: set[str], limit: int = 10):
        terms = query.casefold().split()
        hits = []
        for chunk in self.chunks.values():
            document = self.documents.get(chunk.doc_id)
            if not document or (document.visibility == "private" and document.project_id not in allowed_project_ids):
                continue
            score = sum(chunk.text.casefold().count(term) for term in terms)
            if score:
                hits.append((score, chunk))
        return [c for _, c in sorted(hits, key=lambda x: (-x[0], x[1].id))[:limit]]


class PersistentIndex:
    def __init__(self, engine: Any, qdrant: QdrantStore, embedder: EmbeddingBackend, settings: Any):
        self.engine, self.qdrant, self.embedder, self.settings = engine, qdrant, embedder, settings

    def reconcile(self, root: Path) -> list[VaultError]:
        documents, errors = scan_vault(root)
        session = session_factory(self.engine)()
        try:
            existing = {row.id: row for row in session.scalars(select(DocumentRow)).all()}
            incoming = {doc.id: doc for doc in documents}
            for doc_id in set(existing) - set(incoming):
                ids = list(session.scalars(select(ChunkRow.id).where(ChunkRow.doc_id == doc_id)))
                self.qdrant.delete(ids)
                session.execute(delete(ChunkRow).where(ChunkRow.doc_id == doc_id))
                session.delete(existing[doc_id])
            for doc in documents:
                row = existing.get(doc.id)
                if row and row.content_hash == doc.content_hash and row.path == doc.path:
                    continue
                if row:
                    old_ids = list(session.scalars(select(ChunkRow.id).where(ChunkRow.doc_id == doc.id)))
                    self.qdrant.delete(old_ids)
                    session.execute(delete(ChunkRow).where(ChunkRow.doc_id == doc.id))
                else:
                    row = DocumentRow(id=doc.id)
                    session.add(row)
                row.project_id, row.path, row.title, row.type, row.visibility = (
                    doc.project_id,
                    doc.path,
                    doc.title,
                    doc.type,
                    doc.visibility,
                )
                row.content, row.content_hash, row.updated_at = doc.content, doc.content_hash, doc.updated_at
                chunks = chunk_document(doc, self.settings.chunk_size, self.settings.chunk_overlap)
                vectors = self.embedder.embed([c.text for c in chunks])
                if vectors:
                    self.qdrant.ensure_collection(len(vectors[0]))
                points = []
                for chunk, vector in zip(chunks, vectors):
                    session.add(
                        ChunkRow(
                            id=chunk.id,
                            doc_id=doc.id,
                            heading=chunk.heading,
                            heading_path=chunk.heading_path,
                            content=chunk.text,
                            content_hash=chunk.content_hash,
                            line_start=chunk.line_start,
                            line_end=chunk.line_end,
                            embedding_model=self.embedder.model,
                            embedding_version=self.embedder.version,
                        )
                    )
                    points.append(
                        (
                            chunk.id,
                            vector,
                            {
                                "project_id": doc.project_id,
                                "visibility": doc.visibility,
                                "doc_id": doc.id,
                                "chunk_id": chunk.id,
                            },
                        )
                    )
                self.qdrant.upsert(points)
            session.execute(delete(DocumentLinkRow))
            for document in documents:
                for link in extract_links(document.content):
                    target = resolve_link(link, document.path, documents)
                    session.add(
                        DocumentLinkRow(
                            source_document_id=document.id,
                            target_document_id=target.id if target else None,
                            target_ref=link.target,
                            target_title=target.title if target else link.target,
                            target_path=target.path if target else None,
                            embedded=link.embedded,
                            link_type="embed" if link.embedded else ("markdown" if link.relative else "wiki"),
                        )
                    )
            session.execute(delete(IndexErrorRow))
            session.add_all([IndexErrorRow(path=e.path, reason=e.reason) for e in errors])
            session.commit()
        finally:
            session.close()
        return errors
