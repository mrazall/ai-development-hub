from mcp_knowledge import server


def test_all_required_tools_are_registered():
    names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert names == {
        "knowledge.search",
        "knowledge.read",
        "knowledge.context",
        "knowledge.decisions",
        "knowledge.index_status",
        "knowledge.handoff.create",
        "knowledge.handoff.get",
        "knowledge.write_draft",
        "knowledge.propose_update",
    }


def test_search_schema_has_safe_limits():
    tool = next(tool for tool in server.mcp._tool_manager.list_tools() if tool.name == "knowledge.search")
    schema = tool.parameters
    assert schema["properties"]["query"]["minLength"] == 1
    assert schema["properties"]["limit"]["minimum"] == 1
    assert schema["properties"]["limit"]["maximum"] == 100


def test_renewed_token_file_wins_over_the_start_time_env(monkeypatch, tmp_path):
    from mcp_knowledge import server

    token_file = tmp_path / "hub-token"
    token_file.write_text("renewed-token\n", encoding="utf-8")
    monkeypatch.setenv("AIHUB_HUB_URL", "http://hub.test")
    monkeypatch.setenv("AIHUB_HUB_TOKEN", "expired-token")
    monkeypatch.setenv("AIHUB_HUB_TOKEN_FILE", str(token_file))
    seen = {}
    monkeypatch.setattr(server, "KnowledgeClient", lambda url, **kwargs: seen.update(url=url, **kwargs) or object())
    server._client()
    assert seen["hub_token"] == "renewed-token"
