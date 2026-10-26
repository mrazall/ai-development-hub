from __future__ import annotations

from typing import Any


class QdrantStore:
    """Small adapter keeping ACL filters at the vector query boundary."""

    def __init__(self, client: Any, collection: str):
        self.client, self.collection = client, collection

    @staticmethod
    def collection_name(model: str, version: str) -> str:
        safe = "".join(char if char.isalnum() else "_" for char in model).strip("_")
        return f"knowledge_{safe}_{version}"

    def search(self, vector: list[float], allowed_project_ids: set[str], limit: int = 10, admin: bool = False):
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        should = [FieldCondition(key="visibility", match=MatchAny(any=["shared", "public"]))]
        if allowed_project_ids:
            should.insert(0, FieldCondition(key="project_id", match=MatchAny(any=list(allowed_project_ids))))
        query_filter = None if admin else Filter(should=should)
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return response.points

    def ensure_collection(self, dimensions: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection, vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE)
            )

    def upsert(self, points: list[tuple[str, list[float], dict[str, object]]]) -> None:
        from qdrant_client.models import PointStruct

        if points:
            self.client.upsert(
                self.collection,
                points=[PointStruct(id=key, vector=vector, payload=payload) for key, vector, payload in points],
            )

    def delete(self, ids: list[str]) -> None:
        if ids:
            self.client.delete(self.collection, points_selector=ids)
