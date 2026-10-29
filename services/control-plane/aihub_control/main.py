import asyncio
import json
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from urllib.parse import parse_qsl, urlencode
from sqlalchemy import text

from . import API_VERSION
from .auth import db_dep
from .config import Settings
from .db import get_session_factory
from .deps import offline_loop
from .routers import accounts, auth, dashboard, events, knowledge, projects, sessions, tasks, users, workers
from .routers import assignments, graph, notifications
from .routers import chats
from .routers import mcp, approvals, backups, attachments, limits
from .routers import orchestrations
from .routers import terminal
from .routers import system
from .routers import orchestration_view
from .orchestration.lifecycle import purge_expired
from .orchestration.auto_resume import resume_due
from .health import collect as collect_health, notify_changes
from .system_settings import get_setting

settings = Settings()


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(offline_loop())
    retention_task = asyncio.create_task(_retention_loop())
    resume_task = asyncio.create_task(_resume_loop())
    health_task = asyncio.create_task(_health_loop())
    yield
    task.cancel()
    retention_task.cancel()
    resume_task.cancel()
    health_task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    try:
        await retention_task
    except asyncio.CancelledError:
        pass


def _purge_once() -> None:
    _, factory = get_session_factory()
    db = factory()
    try:
        purge_expired(db)
    finally:
        db.close()


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        await asyncio.to_thread(_purge_once)


def _resume_once() -> None:
    _, factory = get_session_factory()
    db = factory()
    try:
        resume_due(db)
    finally:
        db.close()


async def _resume_loop() -> None:
    # Sessions stopped by a provider limit continue once it is refilled.
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(_resume_once)
        except Exception as exc:  # a bad tick must not kill the loop
            print(f"auto-resume failed: {exc}", flush=True)


def _health_once() -> int:
    """One round of checks; returns the interval to wait (it can be changed in the panel)."""
    _, factory = get_session_factory()
    db = factory()
    try:
        interval = int(get_setting(db, "health_interval_s"))
        if interval > 0:
            notify_changes(db, collect_health(db))
        return interval
    finally:
        db.close()


async def _health_loop() -> None:
    # Failures (worker offline, Tailscale down, stale backups…) become notifications without opening the page.
    await asyncio.sleep(90)  # let workers re-register their heartbeat after a restart
    while True:
        interval = 60
        try:
            interval = await asyncio.to_thread(_health_once)
        except Exception as exc:  # a bad tick must not kill the loop
            print(f"health check failed: {exc}", flush=True)
        await asyncio.sleep(interval if interval > 0 else 300)  # off: look again in 5 min


app = FastAPI(title="AI Development Hub Control Plane", version=API_VERSION, lifespan=lifespan)
api = FastAPI()
api.include_router(auth.router)
api.include_router(system.router)
api.include_router(orchestration_view.router)
api.include_router(projects.router)
api.include_router(tasks.router)
api.include_router(workers.router)
api.include_router(sessions.router)
api.include_router(events.router)
api.include_router(knowledge.router)
api.include_router(users.router)
api.include_router(dashboard.router)
api.include_router(accounts.router)  # accounts & model connections
api.include_router(assignments.router)
api.include_router(graph.router)
api.include_router(notifications.router)
api.include_router(mcp.router)  # MCP registry and config generation
api.include_router(approvals.router)  # approval requests and decisions
api.include_router(backups.router)  # backup reports and status
api.include_router(attachments.router)  # upload/download lifecycle
api.include_router(chats.router)  # personal chat chains
api.include_router(limits.router)  # account limits
api.include_router(limits.accounts_router)  # account limits worker endpoints
api.include_router(orchestrations.router)  # orchestration API
api.include_router(terminal.router)  # embedded terminal relay (WebSocket)


@api.get("/health")
def health(db=Depends(db_dep)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, "database unavailable") from exc
    return {"status": "ok", "db": True, "schema_version": 1, "api_version": API_VERSION}


app.mount("/api/v0", api)


@app.middleware("http")
async def security_and_ticket_middleware(request: Request, call_next):
    query = dict(parse_qsl(request.scope.get("query_string", b"").decode(), keep_blank_values=True))
    ticket = query.get("ticket")
    if ticket:
        request.scope["aihub_stream_ticket"] = ticket
        # Ticket is consumed by the endpoint; scrub it from the ASGI scope before access logging.
        query.pop("ticket", None)
        request.scope["query_string"] = urlencode(query).encode()
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            request.scope["aihub_stream_user"] = None
        # The stream endpoint resolves ownership from the ticket only after a user id is supplied.
        # Ticket ownership is encoded in the in-memory store, so pass a safe marker here.
        from .tickets import owner_for
        request.scope["aihub_stream_user"] = owner_for(ticket)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.url.path.startswith("/api/"):
        frames = settings.frame_src.strip() or "'none'"
        response.headers.setdefault("Content-Security-Policy", f"default-src 'self'; connect-src 'self' ipc: http://ipc.localhost; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-src {frames}; frame-ancestors 'none'")
    return response


def _desktop_dir() -> Path:
    return Path(settings.data_dir).expanduser() / "desktop"


@app.get("/desktop/latest.json")
def desktop_latest():
    """What the desktop app's updater reads. Installers are signed; the app checks the signature itself."""
    path = _desktop_dir() / "latest.json"
    if not path.is_file():
        raise HTTPException(404, "no desktop release")
    data = json.loads(path.read_text(encoding="utf-8"))
    base = settings.public_url.rstrip("/")
    for platform in (data.get("platforms") or {}).values():
        url = str(platform.get("url", ""))
        if url and not url.startswith(("https://", "http://")):
            platform["url"] = f"{base}/desktop/{url}"
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@app.get("/desktop/{name}")
def desktop_file(name: str):
    path = _desktop_dir() / name
    if not re.fullmatch(r"[\w .()+-]+\.(exe|sig)", name) or not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, filename=name)


@app.get("/{path:path}")
def spa(path: str):
    web_dir = Path(settings.web_dir)
    if not web_dir.is_dir():
        raise HTTPException(404, "web application is not installed")
    candidate = (web_dir / path).resolve()
    if candidate.is_file() and web_dir.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = web_dir / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(404, "web application is not installed")
