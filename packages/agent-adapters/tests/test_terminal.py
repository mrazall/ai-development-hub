import asyncio
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PTY needs a POSIX worker")


def test_shell_runs_in_workdir_and_rejects_paths_outside_project(tmp_path):
    from aihub_agents.terminal import TerminalChannel

    async def scenario():
        channel = TerminalChannel("https://hub.example", "worker-a", lambda: "token")
        assert channel.url == "wss://hub.example/api/v0/workers/worker-a/terminal-channel"
        sent = []

        async def send(frame):
            sent.append(frame)

        workdir = tmp_path / "project"
        await channel._handle({"t": "open", "tid": "t1", "workdir": str(workdir), "allowed_paths": [str(tmp_path)]}, send)
        assert sent[-1] == {"t": "ready", "tid": "t1"}
        await channel._handle({"t": "i", "tid": "t1", "d": "pwd; echo done-$((40+2))\n"}, send)
        for _ in range(100):
            output = "".join(frame.get("d", "") for frame in sent if frame["t"] == "o")
            if "done-42" in output:
                break
            await asyncio.sleep(0.05)
        assert "done-42" in output and str(workdir) in output
        await channel._handle({"t": "close", "tid": "t1"}, send)
        assert "t1" not in channel._shells

        await channel._handle({"t": "open", "tid": "t2", "workdir": "/etc", "allowed_paths": [str(tmp_path)]}, send)
        assert sent[-1]["t"] == "x" and sent[-1]["tid"] == "t2"
        assert "t2" not in channel._shells

    asyncio.run(scenario())
