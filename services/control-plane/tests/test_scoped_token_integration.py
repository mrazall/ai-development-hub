"""Chat memory tokens: a scoped token must open the knowledge read/draft endpoints and nothing else."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from test_api_integration import admin_token, auth, client, clean_schema
from aihub_control.auth import issue_scoped_token
from aihub_control.config import Settings
from aihub_control.db import get_session_factory
from aihub_control.models import User

pytestmark = pytest.mark.integration


def _admin():
    _, factory = get_session_factory()
    db = factory()
    try:
        return db.query(User).filter_by(username="admin").one()
    finally:
        db.close()


def _scoped(scopes, ttl=3600):
    return issue_scoped_token(_admin(), scopes, ttl=ttl, settings=Settings()).access_token


def test_scoped_token_cannot_reach_anything_but_knowledge(client, admin_token):  # noqa: F811
    token = _scoped({"knowledge:read", "knowledge:draft"})
    for path in ("/api/v0/projects", "/api/v0/sessions", "/api/v0/accounts", "/api/v0/workers", "/api/v0/chats",
                 "/api/v0/limits", "/api/v0/knowledge/graph"):
        assert client.get(path, headers=auth(token)).status_code in (401, 403), path
    assert client.post("/api/v0/projects", headers=auth(token), json={"id": "x1", "name": "x"}).status_code in (401, 403)
    # Knowledge search passes authentication (the knowledge backend may be absent in tests → 5xx, never 401/403).
    assert client.get("/api/v0/knowledge/search?q=vds", headers=auth(token)).status_code not in (401, 403)


def test_read_only_scope_cannot_create_drafts(client, admin_token):  # noqa: F811
    token = _scoped({"knowledge:read"})
    response = client.post("/api/v0/knowledge/drafts", headers=auth(token), json={"title": "t", "content": "c"})
    assert response.status_code == 403


def test_scoped_ttl_is_capped_and_expired_token_is_rejected(client, admin_token):  # noqa: F811
    token = issue_scoped_token(_admin(), {"knowledge:read"}, ttl=86400, settings=Settings())
    assert token.expires_in <= 3600
    expired = jwt.encode(
        {"sub": _admin().id, "role": "admin", "scope": "knowledge:read",
         "exp": datetime.now(timezone.utc) - timedelta(seconds=5)},
        Settings().secret_key, algorithm="HS256",
    )
    assert client.get("/api/v0/knowledge/search?q=vds", headers=auth(expired)).status_code == 401
