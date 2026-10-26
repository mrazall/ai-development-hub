from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from aihub_knowledge import api
from aihub_knowledge.acl import Principal, sign_principal
from aihub_knowledge.api import clean_excerpt
from aihub_knowledge.db import DocumentRow, session_factory


def test_clean_excerpt_removes_markdown_and_obsidian_controls():
    text = "# 📌 Заголовок\n> [!note] Важно\nТекст **жирный** [[Другой файл|ссылка]] и [веб](https://example.test)."
    assert clean_excerpt(text) == "📌 Заголовок Важно Текст жирный ссылка и веб."


def test_api_rejects_missing_and_forged_principal():
    client = TestClient(api.app)
    assert client.get("/search", params={"query": "anything"}).status_code == 401
    assert (
        client.get("/search", params={"query": "anything"}, headers={"X-AIHub-Principal": "v1.bad.sig"}).status_code
        == 401
    )


def test_api_search_passes_server_verified_principal(monkeypatch):
    captured = {}

    class Searcher:
        last_vector_error = None

        def search(self, query, principal, limit):
            captured.update(query=query, principal=principal, limit=limit)
            return [{"project_id": next(iter(principal.project_ids)), "match": "lexical"}]

    monkeypatch.setattr(api.settings, "internal_secret", "review-secret")
    monkeypatch.setattr(api, "searcher", Searcher())
    principal = Principal("viewer-1", "viewer", frozenset({"alpha"}))
    header = sign_principal(principal, "review-secret")
    response = TestClient(api.app).get("/search", params={"query": "needle"}, headers={"X-AIHub-Principal": header})
    assert response.status_code == 200
    assert response.json()["hits"][0]["project_id"] == "alpha"
    assert captured["principal"] == principal


def test_api_viewer_cannot_reconcile(monkeypatch):
    monkeypatch.setattr(api.settings, "internal_secret", "review-secret")
    monkeypatch.setattr(api, "indexer", object())
    header = sign_principal(Principal("viewer-1", "viewer", frozenset({"alpha"})), "review-secret")
    response = TestClient(api.app).post("/index/reconcile", headers={"X-AIHub-Principal": header})
    assert response.status_code == 403


@pytest.mark.integration
def test_api_private_document_from_foreign_project_is_not_readable(monkeypatch):
    monkeypatch.setattr(api.settings, "internal_secret", "review-secret")
    with session_factory(api.engine)() as session:
        session.merge(
            DocumentRow(
                id="api-foreign",
                project_id="beta",
                path="api-foreign.md",
                title="foreign",
                visibility="private",
                content="private",
                content_hash="a" * 64,
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
    try:
        header = sign_principal(Principal("viewer-1", "viewer", frozenset({"alpha"})), "review-secret")
        response = TestClient(api.app).get("/documents/api-foreign", headers={"X-AIHub-Principal": header})
        assert response.status_code == 404
    finally:
        with session_factory(api.engine)() as session:
            session.query(DocumentRow).filter_by(id="api-foreign").delete()
            session.commit()
