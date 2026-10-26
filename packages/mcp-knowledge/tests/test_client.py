import pytest
import httpx

from mcp_knowledge.client import KnowledgeClient


def test_client_forwards_principal_and_maps_context():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers["x-aihub-principal"]))
        if request.url.path == "/search":
            return httpx.Response(200, json={"hits": [{"doc_id": "one"}]})
        if request.url.path == "/documents/one":
            return httpx.Response(200, json={"id": "one", "content": "text"})
        raise AssertionError(request.url)

    client = KnowledgeClient("http://knowledge", "signed-principal", httpx.MockTransport(handler))
    try:
        result = client.context("needle", 1)
    finally:
        client.close()
    assert result["documents"] == [{"id": "one", "content": "text"}]
    assert seen == [
        ("GET", "/search", "signed-principal"),
        ("GET", "/documents/one", "signed-principal"),
    ]


def test_client_does_not_expose_api_secret_in_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "project access required"})

    client = KnowledgeClient("http://knowledge", "signed", httpx.MockTransport(handler))
    try:
        try:
            client.write_draft("alpha", "x", "secret-looking content")
        except RuntimeError as exc:
            assert "secret-looking content" not in str(exc)
            assert "project access required" in str(exc)
        else:
            raise AssertionError("expected error")
    finally:
        client.close()


def test_client_does_not_expose_non_json_error_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="upstream secret=do-not-leak")

    client = KnowledgeClient("http://knowledge", "signed", httpx.MockTransport(handler))
    client._sleep = lambda _seconds: None  # 502 is retried; no real waiting in tests
    try:
        try:
            client.index_status()
        except RuntimeError as exc:
            assert "do-not-leak" not in str(exc)
            assert "Bad Gateway" in str(exc)
        else:
            raise AssertionError("expected error")
    finally:
        client.close()


def test_client_quotes_document_id_path():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path)
        return httpx.Response(200, json={"id": "a/b"})

    client = KnowledgeClient("http://knowledge", "signed", httpx.MockTransport(handler))
    try:
        client.read("a/b")
    finally:
        client.close()
    assert seen == [b"/documents/a%2Fb"]


def test_hub_restart_is_retried_but_client_errors_are_not():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) < 3:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json={"results": []})

    client = KnowledgeClient("http://knowledge", "signed", httpx.MockTransport(handler))
    client._sleep = lambda _seconds: None
    assert client.search("x") == {"results": []}
    assert len(calls) == 3

    def forbidden(request):
        calls.append("403")
        return httpx.Response(403, json={"detail": "forbidden"})

    client = KnowledgeClient("http://knowledge", "signed", httpx.MockTransport(forbidden))
    client._sleep = lambda _seconds: None
    calls.clear()
    with pytest.raises(RuntimeError, match="403"):
        client.search("x")
    assert calls == ["403"]
