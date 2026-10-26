"""The permission prompt tool, over real stdio MCP: Claude Code accepts only a single text block holding
{"behavior": "allow"|"deny", ...}. Found live: a structured copy next to the text made Claude reject it."""
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _fake_hub(decision: str) -> HTTPServer:
    class Hub(BaseHTTPRequestHandler):
        def _answer(self, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(201 if self.command == "POST" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self._answer({"id": "a1", "status": decision})

        def do_GET(self):  # noqa: N802
            self._answer({"id": "a1", "status": decision})

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Hub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def _call(decision: str):
    hub = _fake_hub(decision)
    params = StdioServerParameters(command=sys.executable, args=["-c", "from mcp_knowledge.server import main; main()"], env={
        **os.environ, "AIHUB_HUB_URL": f"http://127.0.0.1:{hub.server_port}", "AIHUB_HUB_TOKEN": "t",
        "AIHUB_PERMISSION_SESSION": "s1", "AIHUB_MCP_TOOLSET": "lean",
    })
    try:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool("permission_request", {"tool_name": "Bash", "input": {"command": "ls"}})
    finally:
        hub.shutdown()


def test_allow_is_a_single_text_block():
    result = asyncio.run(_call("approved"))
    assert len(result.content) == 1 and result.content[0].type == "text"
    assert result.structuredContent is None
    assert json.loads(result.content[0].text) == {"behavior": "allow", "updatedInput": {"command": "ls"}}


def test_reject_denies():
    result = asyncio.run(_call("rejected"))
    assert json.loads(result.content[0].text)["behavior"] == "deny"
