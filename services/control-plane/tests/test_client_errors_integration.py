"""A crash in the panel reaches the hub log, size-capped, without tokens, and cannot flood it."""
import logging

import pytest

from test_api_integration import admin_token, auth, clean_schema, client

pytestmark = pytest.mark.integration


def test_client_errors_are_logged_redacted_and_rate_limited(client, admin_token, caplog):  # noqa: F811
    body = {"message": "Cannot read properties of undefined (reading 'online')", "stack": "at Dashboard",
            "where": "page", "path": "/", "viewport": "390x844", "user_agent": "Mobile Safari"}
    with caplog.at_level(logging.WARNING, logger="aihub.client"):
        assert client.post("/api/v0/client-errors", headers=auth(admin_token), json=body).status_code == 204
        leaked = {**body, "message": "token ghp_" + "A" * 36}
        client.post("/api/v0/client-errors", headers=auth(admin_token), json=leaked)
        for _ in range(20):
            client.post("/api/v0/client-errors", headers=auth(admin_token), json=body)
    lines = [record.getMessage() for record in caplog.records if record.name == "aihub.client"]
    assert "reading 'online'" in lines[0] and "390x844" in lines[0]
    assert all("A" * 36 not in line for line in lines)
    assert len(lines) == 10  # at most ten a minute per user
    assert client.post("/api/v0/client-errors", json=body).status_code == 401
