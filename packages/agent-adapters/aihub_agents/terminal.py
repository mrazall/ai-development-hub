"""Worker side of the embedded terminal: one outgoing channel to the hub, a shell PTY per terminal.

The hub relays browser frames (see control-plane routers/terminal.py). Each `open` starts
`bash -l` in the session workdir, which must lie inside the project's allowed paths.
"""

import asyncio
import codecs
import fcntl
import json
import os
import pty
import signal
import struct
import termios
from typing import Any

from .adapters import ensure_allowed_workdir

OUTPUT_BATCH_SECONDS = 0.015  # coalesce PTY output into ~60 frames/s at most
READ_SIZE = 65536


def _set_size(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class _Shell:
    def __init__(self, tid: str, workdir: str, cols: int, rows: int, send):
        self.tid, self._send = tid, send
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending: list[str] = []
        self._flush_handle: asyncio.TimerHandle | None = None
        pid, fd = pty.fork()
        if pid == 0:  # child: become a login shell in the workdir
            try:
                os.chdir(workdir)
                env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
                os.execvpe("bash", ["bash", "-l"], env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        _set_size(fd, cols, rows)
        os.set_blocking(fd, False)
        asyncio.get_running_loop().add_reader(fd, self._on_readable)

    def _on_readable(self) -> None:
        try:
            data = os.read(self.fd, READ_SIZE)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:  # the shell exited
            self.close()
            asyncio.ensure_future(self._send({"t": "x", "tid": self.tid, "reason": "exited"}))
            return
        self._pending.append(self._decoder.decode(data))
        if self._flush_handle is None:
            self._flush_handle = asyncio.get_running_loop().call_later(OUTPUT_BATCH_SECONDS, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        text, self._pending = "".join(self._pending), []
        if text:
            asyncio.ensure_future(self._send({"t": "o", "tid": self.tid, "d": text}))

    def write(self, text: str) -> None:
        try:
            os.write(self.fd, text.encode())
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        try:
            _set_size(self.fd, cols, rows)
        except OSError:
            pass

    def close(self) -> None:
        if self.fd < 0:
            return
        loop = asyncio.get_running_loop()
        loop.remove_reader(self.fd)
        if self._flush_handle:
            self._flush_handle.cancel()
            self._flush()
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = -1
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pass


class TerminalChannel:
    """Keeps the hub channel open (with reconnect) and serves terminal frames."""

    def __init__(self, base_url: str, worker_id: str, token_provider):
        scheme = "wss" if base_url.startswith("https") else "ws"
        self.url = f"{scheme}{base_url[base_url.index(':'):].rstrip('/')}/api/v0/workers/{worker_id}/terminal-channel"
        self._token = token_provider
        self._shells: dict[str, _Shell] = {}

    async def run(self) -> None:
        import websockets  # optional at import time so the worker starts without it

        delay = 1
        while True:
            try:
                async with websockets.connect(
                    self.url, additional_headers={"Authorization": f"Bearer {self._token()}"},
                    max_size=2**22, ping_interval=20,
                ) as socket:
                    delay = 1
                    lock = asyncio.Lock()

                    async def send(frame: dict[str, Any]) -> None:
                        async with lock:
                            try:
                                await socket.send(json.dumps(frame))
                            except websockets.ConnectionClosed:
                                pass

                    async for raw in socket:
                        await self._handle(json.loads(raw), send)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - network errors of any kind: reconnect
                pass
            finally:
                for shell in list(self._shells.values()):
                    shell.close()
                self._shells.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def _handle(self, frame: dict[str, Any], send) -> None:
        tid = str(frame.get("tid", ""))
        kind = frame.get("t")
        if kind == "open":
            try:
                workdir = ensure_allowed_workdir(frame.get("workdir", ""), frame.get("allowed_paths", []))
                os.makedirs(workdir, exist_ok=True)
                self._shells[tid] = _Shell(tid, workdir, int(frame.get("c", 80)), int(frame.get("r", 24)), send)
            except (OSError, ValueError, TypeError) as exc:
                await send({"t": "x", "tid": tid, "reason": f"cannot open: {exc}"[:200]})
                return
            await send({"t": "ready", "tid": tid})
        elif kind == "i" and tid in self._shells:
            self._shells[tid].write(str(frame.get("d", "")))
        elif kind == "z" and tid in self._shells:
            self._shells[tid].resize(int(frame.get("c", 80)), int(frame.get("r", 24)))
        elif kind == "close" and tid in self._shells:
            self._shells.pop(tid).close()
