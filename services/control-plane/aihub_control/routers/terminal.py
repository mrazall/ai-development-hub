"""Embedded terminal: relays a browser WebSocket to a shell PTY on the session's worker.

The browser cannot reach the worker, so both sides connect here:
- each worker keeps one outgoing channel (`/workers/{id}/terminal-channel`, worker token);
- a browser opens `/terminal/{session_id}/ws` and authenticates with a single-use stream ticket
  sent as the first frame (never in the URL: access logs record WebSocket URLs).
Frames are JSON text. Browser: i (input), z (resize) → hub; ready, o (output), x (closed) ← hub.
Worker: open, i, z, close ← hub; ready, o, x → hub, every frame tagged with the terminal id.
State lives in this process only, which matches the single control-plane instance.
"""

import asyncio
import json
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import _worker_token
from ..db import get_session_factory
from ..models import AuditLog, Project, Session, User
from ..tickets import consume, owner_for

router = APIRouter(tags=["terminal"])

MAX_INPUT = 64 * 1024  # one paste; larger frames are dropped


class _Peer:
    """A WebSocket with serialized sends: several coroutines write to the same socket."""

    def __init__(self, socket: WebSocket):
        self.socket = socket
        self._lock = asyncio.Lock()

    async def send(self, frame: dict) -> None:
        async with self._lock:
            await self.socket.send_text(json.dumps(frame))


_workers: dict[str, _Peer] = {}
_terminals: dict[str, tuple[str, _Peer]] = {}  # terminal id -> (worker id, browser)


def _db():
    _, factory = get_session_factory()
    return factory()


async def _close_browser(tid: str, reason: str) -> None:
    item = _terminals.pop(tid, None)
    if not item:
        return
    try:
        await item[1].send({"t": "x", "reason": reason})
        await item[1].socket.close()
    except (RuntimeError, WebSocketDisconnect):
        pass


@router.websocket("/workers/{worker_id}/terminal-channel")
async def worker_channel(socket: WebSocket, worker_id: str):
    header = socket.headers.get("authorization", "")
    db = _db()
    try:
        record = _worker_token(db, header[7:]) if header.lower().startswith("bearer ") else None
    finally:
        db.close()
    if not record or record.worker_id != worker_id:
        await socket.close(code=4401)
        return
    await socket.accept()
    peer = _Peer(socket)
    previous = _workers.get(worker_id)
    _workers[worker_id] = peer
    if previous:
        try:
            await previous.socket.close()
        except RuntimeError:
            pass
    try:
        while True:
            frame = json.loads(await socket.receive_text())
            tid = str(frame.get("tid", ""))
            item = _terminals.get(tid)
            if not item or item[0] != worker_id:
                continue
            if frame.get("t") == "x":
                await _close_browser(tid, str(frame.get("reason", "closed"))[:200])
            elif frame.get("t") in {"o", "ready"}:
                try:
                    await item[1].send({"t": frame["t"], **({"d": frame.get("d", "")} if frame["t"] == "o" else {})})
                except (RuntimeError, WebSocketDisconnect):
                    pass
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        if _workers.get(worker_id) is peer:
            del _workers[worker_id]
            for tid, (owner, _) in list(_terminals.items()):
                if owner == worker_id:
                    await _close_browser(tid, "worker_offline")


@router.websocket("/terminal/{session_id}/ws")
async def browser_terminal(socket: WebSocket, session_id: str):
    await socket.accept()
    browser = _Peer(socket)
    try:
        first = json.loads(await asyncio.wait_for(socket.receive_text(), timeout=10))
    except (TimeoutError, WebSocketDisconnect, json.JSONDecodeError):
        await socket.close(code=4401)
        return
    ticket = str(first.get("ticket", "")) if first.get("t") == "auth" else ""
    owner = owner_for(ticket) if ticket else None
    if not owner or not consume(ticket, owner):
        await browser.send({"t": "x", "reason": "unauthorized"})
        await socket.close(code=4401)
        return
    db = _db()
    try:
        user = db.get(User, owner)
        session = db.get(Session, session_id)
        # A terminal is shell access on the worker machine: admins only.
        if not user or user.role != "admin":
            reason = "forbidden"
        elif not session:
            reason = "not_found"
        else:
            reason = ""
            project = db.get(Project, session.project_id)
            open_frame = {
                "t": "open", "session_id": session.id, "workdir": session.workdir,
                "allowed_paths": list(project.allowed_paths or []) if project else [],
            }
            worker_id = session.worker_id
            db.add(AuditLog(user_id=user.id, action="terminal.open", target=session.id))
            db.commit()
    finally:
        db.close()
    if reason:
        await browser.send({"t": "x", "reason": reason})
        await socket.close()
        return
    worker = _workers.get(worker_id)
    if not worker:
        await browser.send({"t": "x", "reason": "worker_offline"})
        await socket.close()
        return
    tid = str(uuid4())
    _terminals[tid] = (worker_id, browser)
    try:
        await worker.send({**open_frame, "tid": tid, "c": 80, "r": 24})
        while True:
            frame = json.loads(await socket.receive_text())
            kind = frame.get("t")
            if kind == "i" and isinstance(frame.get("d"), str) and len(frame["d"]) <= MAX_INPUT:
                await worker.send({"t": "i", "tid": tid, "d": frame["d"]})
            elif kind == "z":
                cols, rows = int(frame.get("c", 0)), int(frame.get("r", 0))
                if 1 <= cols <= 500 and 1 <= rows <= 300:
                    await worker.send({"t": "z", "tid": tid, "c": cols, "r": rows})
    except (WebSocketDisconnect, json.JSONDecodeError, ValueError, TypeError, RuntimeError):
        pass
    finally:
        if _terminals.pop(tid, None):
            current = _workers.get(worker_id)
            if current:
                try:
                    await current.send({"t": "close", "tid": tid})
                except (RuntimeError, WebSocketDisconnect):
                    pass
