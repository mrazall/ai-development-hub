from __future__ import annotations

import logging
import os

import httpx
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy import func, or_, select

from .acl import Principal
from .db import ChunkRow, DocumentRow, session_factory
from .embeddings import EmbeddingBackend
from .qdrant_store import QdrantStore
from .search import RankedItem, reciprocal_rank_fusion

logger = logging.getLogger(__name__)


def _visible(row: DocumentRow, principal: Principal) -> bool:
    return (
        principal.is_admin
        or row.visibility in {"shared", "public"}
        or (row.project_id is not None and row.project_id in principal.project_ids)
    )


# Nearest neighbours always exist, so a vector-only hit (no word overlap) must be clearly similar.
# Measured 25.10 on the owner's vault with qwen3-embedding: gibberish tops out at 0.50-0.64,
# meaningful paraphrases reach 0.65-0.76. Hits that also match lexically are never filtered.
DEFAULT_VECTOR_ONLY_MIN_SCORE = 0.65


class HybridSearcher:
    def __init__(self, engine, qdrant: QdrantStore, embedder: EmbeddingBackend, vector_only_min_score: float | None = None):
        self.engine, self.qdrant, self.embedder = engine, qdrant, embedder
        self.vector_only_min_score = (
            vector_only_min_score
            if vector_only_min_score is not None
            else float(os.environ.get("AIHUB_VECTOR_ONLY_MIN_SCORE", DEFAULT_VECTOR_ONLY_MIN_SCORE))
        )
        self.last_vector_error: str | None = None

    def search(self, query: str, principal: Principal, limit: int = 10):
        session = session_factory(self.engine)()
        try:
            acl = (
                True
                if principal.is_admin
                else or_(
                    DocumentRow.visibility.in_(["shared", "public"]),
                    DocumentRow.project_id.in_(principal.project_ids),
                )
            )
            lexical: list[RankedItem] = []
            for config, column in (
                ("russian", ChunkRow.fts_russian),
                ("english", ChunkRow.fts_english),
                ("simple", ChunkRow.fts_simple),
            ):
                tsquery = func.websearch_to_tsquery(config, query)
                stmt = (
                    select(ChunkRow, DocumentRow, func.ts_rank_cd(column, tsquery).label("rank"))
                    .join(DocumentRow, ChunkRow.doc_id == DocumentRow.id)
                    .where(column.op("@@")(tsquery))
                )
                if not principal.is_admin:
                    stmt = stmt.where(acl)
                for chunk, doc, rank in session.execute(
                    stmt.order_by(func.ts_rank_cd(column, tsquery).desc()).limit(limit * 3)
                ):
                    lexical.append(RankedItem(chunk.id, (chunk, doc), float(rank)))
            lexical.sort(key=lambda item: (-item.score, item.key))
            lexical = list({item.key: item for item in lexical}.values())
            vector_rank: list[RankedItem] = []
            self.last_vector_error = None
            try:
                vector = self.embedder.embed([query])[0]
                for point in self.qdrant.search(vector, set(principal.project_ids), limit * 3, principal.is_admin):
                    chunk = session.get(ChunkRow, str(point.payload.get("chunk_id", point.id)))
                    doc = session.get(DocumentRow, chunk.doc_id) if chunk else None
                    if chunk and doc and _visible(doc, principal):
                        vector_rank.append(RankedItem(chunk.id, (chunk, doc), float(point.score)))
            except (httpx.HTTPError, ResponseHandlingException, UnexpectedResponse, TimeoutError) as exc:
                self.last_vector_error = type(exc).__name__
                logger.warning("vector search degraded: %s", self.last_vector_error)
                vector_rank = []
            lexical_keys = {item.key for item in lexical}
            vector_rank = [
                item for item in vector_rank
                if item.key in lexical_keys or item.score >= self.vector_only_min_score
            ]
            merged = reciprocal_rank_fusion(lexical[: limit * 3], vector_rank, k=60)
            return [
                self._hit(
                    item,
                    "hybrid"
                    if item.key in {x.key for x in lexical} and item.key in {x.key for x in vector_rank}
                    else "lexical"
                    if item.key in {x.key for x in lexical}
                    else "vector",
                )
                for item in merged[:limit]
            ]
        finally:
            session.close()

    @staticmethod
    def _hit(item: RankedItem, match: str) -> dict[str, object]:
        chunk, doc = item.value
        return {
            "doc_id": doc.id,
            "path": doc.path,
            "title": doc.title,
            "heading": chunk.heading,
            "excerpt": chunk.content[:500],
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "project_id": doc.project_id,
            "updated_at": doc.updated_at,
            "score": item.score,
            "match": match,
        }
