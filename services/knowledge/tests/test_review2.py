from types import SimpleNamespace

from aihub_knowledge.acl import Principal
from aihub_knowledge.qdrant_store import QdrantStore
from aihub_knowledge.search_service import _visible


def test_python_acl_visibility_handles_null_project_without_attribute_error():
    assert _visible(
        SimpleNamespace(project_id="alpha", visibility="private"), Principal("u", "viewer", frozenset({"alpha"}))
    )
    assert not _visible(SimpleNamespace(project_id=None, visibility="private"), Principal("u", "viewer", frozenset()))
    assert _visible(SimpleNamespace(project_id=None, visibility="public"), Principal("u", "viewer", frozenset()))


class QueryPointsClient:
    def query_points(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(points=["point"])


def test_qdrant_store_uses_query_points_and_acl_filter():
    client = QueryPointsClient()
    result = QdrantStore(client, "knowledge_fake").search([0.1], {"alpha"}, 5)
    assert result == ["point"]
    assert client.kwargs["limit"] == 5
    should = client.kwargs["query_filter"].should
    assert {condition.key for condition in should} == {"project_id", "visibility"}
