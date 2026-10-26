"""Ollama response shapes (regression: the real backend always raised KeyError)."""
import httpx
import pytest

from aihub_knowledge import embeddings
from aihub_knowledge.embeddings import OllamaEmbeddingBackend


def _backend(monkeypatch, payload):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    real_client = httpx.Client
    monkeypatch.setattr(embeddings.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    return OllamaEmbeddingBackend("http://ollama:11434", batch_size=2)


def test_api_embed_shape(monkeypatch):
    backend = _backend(monkeypatch, {"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
    assert backend.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_legacy_single_embedding_shape(monkeypatch):
    assert _backend(monkeypatch, {"embedding": [0.5]}).embed(["a"]) == [[0.5]]


def test_unexpected_shape_is_a_clear_error(monkeypatch):
    with pytest.raises(ValueError, match="unexpected Ollama"):
        _backend(monkeypatch, {"error": "model not found"}).embed(["a"])
