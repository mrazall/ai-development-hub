from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy import asc, desc, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from .acl import Principal, parse_principal
from .config import database_url, get_settings
from .db import DocumentLinkRow, DocumentRow, make_engine, session_factory
from .embeddings import FakeEmbeddingBackend, OllamaEmbeddingBackend
from .graph import ghost_id
from .qdrant_store import QdrantStore
from .reconcile import PersistentIndex
from .search_service import HybridSearcher
from .watcher import watch_vault

settings = get_settings()
engine = make_engine(database_url(settings))
try:
    from qdrant_client import QdrantClient

    qdrant = QdrantStore(
        QdrantClient(url=settings.qdrant_url),
        QdrantStore.collection_name(settings.embedding_model, settings.embedding_version),
    )
except (ImportError, RuntimeError, ValueError):
    qdrant = None
embedder = (
    FakeEmbeddingBackend(settings.embedding_model, settings.embedding_version)
    if settings.embed_backend == "fake"
    else OllamaEmbeddingBackend(
        settings.ollama_url, settings.embedding_model, settings.embedding_version, settings.embedding_batch_size
    )
)
indexer = PersistentIndex(engine, qdrant, embedder, settings) if qdrant else None
searcher = HybridSearcher(engine, qdrant, embedder) if qdrant else None


def principal_dependency(x_aihub_principal: str | None = Header(default=None)) -> Principal:
    try:
        return parse_principal(x_aihub_principal, settings.internal_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid principal") from exc


async def _index_then_watch() -> None:
    try:
        await asyncio.to_thread(indexer.reconcile, settings.vault_dir)
    except Exception as exc:  # logged; the watcher retries on the next change
        logging.getLogger(__name__).exception("initial knowledge reconcile failed: %s", type(exc).__name__)
    await watch_vault(settings.vault_dir, lambda _paths: indexer.reconcile(settings.vault_dir))


@asynccontextmanager
async def lifespan(_: FastAPI):
    watcher_task = None
    if indexer:
        try:
            if settings.vault_dir.is_dir():
                # Embedding a whole vault on CPU takes minutes; the API must answer health checks meanwhile.
                watcher_task = asyncio.create_task(_index_then_watch())
        except (
            OSError,
            SQLAlchemyError,
            httpx.HTTPError,
            ResponseHandlingException,
            UnexpectedResponse,
            TimeoutError,
            ValueError,
        ) as exc:
            logging.getLogger(__name__).exception("initial knowledge reconcile failed: %s", type(exc).__name__)
    try:
        yield
    finally:
        if watcher_task:
            watcher_task.cancel()
            await asyncio.gather(watcher_task, return_exceptions=True)


app = FastAPI(title="AI Development Hub Knowledge", version="0.2.0", lifespan=lifespan)


class DraftRequest(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    kind: str = Field(default="draft", pattern=r"^(draft|handoff|proposal)$")
    filename: str | None = Field(default=None, max_length=120)


# Agents write only here: the one writable folder of the vault (the rest is mounted read-only).
DRAFTS_DIR = "_Агенты"
DRAFT_STATUSES = ("new", "applied", "dismissed")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


def _drafts_root() -> Path:
    return (settings.vault_dir.resolve() / DRAFTS_DIR).resolve()


def _draft_path(project_id: str, name: str) -> Path:
    """A draft file by project and file name, never outside the drafts folder."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", project_id) or "/" in name or "\\" in name or not name.endswith(".md"):
        raise HTTPException(status_code=400, detail="invalid draft path")
    base = _drafts_root()
    target = (base / project_id / name).resolve()
    if target.parent != (base / project_id).resolve() or base not in target.parents:
        raise HTTPException(status_code=400, detail="invalid draft path")
    return target


def _read_draft(path: Path) -> dict[str, object]:
    text_value = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = text_value
    match = _FRONTMATTER.match(text_value)
    if match:
        body = text_value[match.end():]
        for line in match.group(1).splitlines():
            key, sep, value = line.partition(":")
            if sep:
                meta[key.strip()] = value.strip().strip("'\"")
    status = meta.get("status", "new")
    return {
        "id": f"{path.parent.name}/{path.name}",
        "project_id": path.parent.name,
        "name": path.name,
        "title": meta.get("title") or path.stem,
        "kind": meta.get("type", "draft"),
        "status": "new" if status == "draft" else status,
        "created_at": meta.get("created_at") or meta.get("updated_at"),
        "applied_commit": meta.get("applied_commit"),
        "content": body.strip(),
    }


def _can_see(principal: Principal, project_id: str) -> bool:
    return principal.is_admin or project_id in principal.project_ids


def _write_vault_draft(request: DraftRequest) -> dict[str, str]:
    """Write a new draft into _Агенты/<project>/, without following user paths."""
    target_dir = (_drafts_root() / request.project_id).resolve()
    if _drafts_root() not in target_dir.parents:
        raise HTTPException(status_code=400, detail="invalid project path")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail="vault is read-only") from exc
    now = datetime.now(UTC)
    # Cyrillic titles stay readable; a timestamp prefix keeps drafts ordered and names unique.
    slug = re.sub(r"[^\w.-]+", "-", request.filename or request.title, flags=re.UNICODE).strip("-.")[:80] or "draft"
    filename = f"{now:%Y%m%d-%H%M%S}-{slug}"
    if not filename.endswith(".md"):
        filename += ".md"
    target = (target_dir / filename).resolve()
    if target.parent != target_dir:
        raise HTTPException(status_code=400, detail="invalid draft filename")
    document = (
        "---\n"
        f"id: draft-{target.stem}\nproject_id: {request.project_id}\n"
        f"type: {request.kind}\ntitle: {request.title!r}\ncreated_at: {now.isoformat()}\n"
        "source: agent\nstatus: new\nvisibility: private\nschema_version: 1\n---\n\n"
        f"{request.content.rstrip()}\n"
    )
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target_dir, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except (UnboundLocalError, OSError):
            pass
        if isinstance(exc, PermissionError):
            raise HTTPException(status_code=409, detail="vault is read-only") from exc
        raise HTTPException(status_code=503, detail="unable to write vault draft") from exc
    return {
        "path": str(target.relative_to(settings.vault_dir.resolve())),
        "id": f"{request.project_id}/{target.name}",
        "status": "new",
    }


@app.get("/drafts")
def list_drafts(principal: Principal = Depends(principal_dependency)):  # noqa: B008
    base = _drafts_root()
    if not base.is_dir():
        return []
    items = []
    for path in sorted(base.glob("*/*.md"), reverse=True):
        if not _can_see(principal, path.parent.name):
            continue
        try:
            draft = _read_draft(path)
        except (OSError, UnicodeDecodeError):
            continue
        content = str(draft.pop("content"))
        items.append({**draft, "preview": content[:400]})
    return items


@app.get("/drafts/{project_id}/{name}")
def get_draft(project_id: str, name: str, principal: Principal = Depends(principal_dependency)):  # noqa: B008
    if not _can_see(principal, project_id):
        raise HTTPException(status_code=403, detail="project access required")
    path = _draft_path(project_id, name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="draft not found")
    return _read_draft(path)


class DraftStatusRequest(BaseModel):
    status: str = Field(pattern=r"^(new|applied|dismissed)$")


@app.post("/drafts/{project_id}/{name}/status")
def set_draft_status(
    project_id: str,
    name: str,
    request: DraftStatusRequest = Body(...),  # noqa: B008
    principal: Principal = Depends(principal_dependency),  # noqa: B008
):
    if not _can_see(principal, project_id):
        raise HTTPException(status_code=403, detail="project access required")
    path = _draft_path(project_id, name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="draft not found")
    text_value = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text_value)
    if match and re.search(r"(?m)^status:.*$", match.group(1)):
        head = re.sub(r"(?m)^status:.*$", f"status: {request.status}", match.group(1), count=1)
    elif match:
        head = f"{match.group(1)}\nstatus: {request.status}"
    else:
        head = f"status: {request.status}"
    updated = f"---\n{head}\n---\n" + (text_value[match.end():] if match else f"\n{text_value}")
    try:
        path.write_text(updated, encoding="utf-8")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail="vault is read-only") from exc
    return _read_draft(path)


@app.post("/drafts", status_code=201)
def write_draft(
    request: DraftRequest = Body(...),  # noqa: B008
    principal: Principal = Depends(principal_dependency),  # noqa: B008
):
    if not principal.is_admin and request.project_id not in principal.project_ids:
        raise HTTPException(status_code=403, detail="project access required")
    return _write_vault_draft(request)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    qdrant_status = "ok"
    if qdrant:
        try:
            qdrant.client.get_collections()
        except (httpx.HTTPError, ResponseHandlingException, UnexpectedResponse, RuntimeError):
            qdrant_status = "degraded"
    else:
        qdrant_status = "degraded"
    return {"status": "ok", "qdrant": qdrant_status}


@app.get("/index/status")
def index_status() -> dict[str, object]:
    session = session_factory(engine)()
    try:
        from .db import ChunkRow, IndexErrorRow

        return {
            "documents": session.query(DocumentRow).count(),
            "chunks": session.query(ChunkRow).count(),
            "queue": 0,
            "errors": session.query(IndexErrorRow).count(),
            "last_error": session.query(IndexErrorRow).order_by(IndexErrorRow.created_at.desc()).first().reason
            if session.query(IndexErrorRow).first()
            else None,
            "model": settings.embedding_model,
            "last_backend_error": searcher.last_vector_error if searcher else None,
            "vault": "ok" if settings.vault_dir.is_dir() else "unavailable",
        }
    finally:
        session.close()


@app.get("/search")
def search(
    query: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    principal: Principal = Depends(principal_dependency),  # noqa: B008
):
    if not searcher:
        raise HTTPException(status_code=503, detail="search backend unavailable")
    return {
        "hits": searcher.search(query, principal, limit),
        "degraded": ["vector"] if searcher.last_vector_error else [],
    }


def _visible_document(doc: DocumentRow, principal: Principal) -> bool:
    return principal.is_admin or doc.visibility in {"shared", "public"} or (
        doc.project_id is not None and doc.project_id in principal.project_ids
    )


_WIKI_LINK = re.compile(r"!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
_MARKDOWN_LINK = re.compile(r"!?\[([^\]]+)\]\([^)]*\)")
_EMOJI_PREFIX = re.compile(r"^(?:[#>*\s]|[-+])+")


def clean_excerpt(text: str, limit: int = 240) -> str:
    """Return a short, readable excerpt without Obsidian/Markdown control syntax."""
    value = re.sub(r"^\s*>?\s*\[!\w+\][+-]?\s*", "", text, flags=re.MULTILINE)
    value = _WIKI_LINK.sub(lambda match: match.group(2) or match.group(1), value)
    value = _MARKDOWN_LINK.sub(r"\1", value)
    value = re.sub(r"[*_`~]", "", value)
    value = re.sub(r"^\s*#+\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*>\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*[-+]\s+", "", value, flags=re.MULTILINE)
    value = _EMOJI_PREFIX.sub("", value)
    return " ".join(value.split())[:limit].strip()


@app.get("/documents")
def documents(
    sort: str = Query(default="updated", pattern="^(updated|title)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    project_id: str | None = Query(default=None, max_length=255),
    type: str | None = Query(default=None, max_length=64),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(principal_dependency),  # noqa: B008
):
    session = session_factory(engine)()
    try:
        stmt = select(DocumentRow)
        if not principal.is_admin:
            stmt = stmt.where(
                or_(
                    DocumentRow.visibility.in_(["shared", "public"]),
                    DocumentRow.project_id.in_(principal.project_ids),
                )
            )
        if project_id:
            stmt = stmt.where(DocumentRow.project_id == project_id)
        if type:
            stmt = stmt.where(DocumentRow.type == type)
        column = DocumentRow.title if sort == "title" else DocumentRow.updated_at
        stmt = stmt.order_by((asc(column) if order == "asc" else desc(column)), asc(DocumentRow.id))
        rows = session.scalars(stmt.offset(offset).limit(limit)).all()
        total_stmt = select(DocumentRow.id)
        if not principal.is_admin:
            total_stmt = total_stmt.where(
                or_(
                    DocumentRow.visibility.in_(["shared", "public"]),
                    DocumentRow.project_id.in_(principal.project_ids),
                )
            )
        if project_id:
            total_stmt = total_stmt.where(DocumentRow.project_id == project_id)
        if type:
            total_stmt = total_stmt.where(DocumentRow.type == type)
        total = len(session.scalars(total_stmt).all())
        return {
            "items": [
                {
                    "id": row.id,
                    "title": row.title,
                    "path": row.path,
                    "project_id": row.project_id,
                    "type": row.type,
                    "updated_at": row.updated_at,
                    "excerpt": clean_excerpt(row.content),
                }
                for row in rows
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    finally:
        session.close()


@app.post("/index/reconcile")
def reconcile(principal: Principal = Depends(principal_dependency)):  # noqa: B008
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")
    if not indexer:
        raise HTTPException(status_code=503, detail="index backend unavailable")
    errors = indexer.reconcile(settings.vault_dir)
    return {"errors": [{"path": e.path, "reason": e.reason} for e in errors]}


@app.get("/documents/{document_id}")
def read_document(document_id: str, principal: Principal = Depends(principal_dependency)):  # noqa: B008
    session = session_factory(engine)()
    try:
        doc = session.get(DocumentRow, document_id)
        if not doc or (
            not principal.is_admin and doc.visibility == "private" and doc.project_id not in principal.project_ids
        ):
            raise HTTPException(status_code=404, detail="document not found")
        return {
            "id": doc.id,
            "project_id": doc.project_id,
            "path": doc.path,
            "title": doc.title,
            "type": doc.type,
            "content": doc.content,
            "visibility": doc.visibility,
            "updated_at": doc.updated_at,
        }
    finally:
        session.close()


@app.get("/graph")
def graph(principal: Principal = Depends(principal_dependency)):  # noqa: B008
    session = session_factory(engine)()
    try:
        documents = session.scalars(select(DocumentRow)).all()
        visible = {
            doc.id: doc
            for doc in documents
            if principal.is_admin
            or doc.visibility in {"shared", "public"}
            or doc.project_id in principal.project_ids
        }
        rows = session.scalars(select(DocumentLinkRow)).all()
        edges: set[tuple[str, str]] = set()
        ghost_data: dict[str, dict[str, object]] = {}
        for row in rows:
            if row.source_document_id not in visible:
                continue
            if row.target_document_id is not None and row.target_document_id not in visible:
                continue
            target_id = row.target_document_id if row.target_document_id in visible else None
            if target_id:
                if target_id != row.source_document_id:
                    edges.add((row.source_document_id, target_id))
            else:
                gid = ghost_id(row.target_ref)
                if gid != row.source_document_id:
                    edges.add((row.source_document_id, gid))
                    ghost_data.setdefault(gid, {"id": gid, "title": row.target_title, "path": None, "project_id": None, "ghost": True})
        degree: dict[str, int] = {}
        for source, target in edges:
            degree[source] = degree.get(source, 0) + 1
            degree[target] = degree.get(target, 0) + 1
        nodes = [
            {"id": doc.id, "title": doc.title, "path": doc.path, "project_id": doc.project_id, "type": doc.type, "degree": degree.get(doc.id, 0), "ghost": False}
            for doc in visible.values()
        ]
        nodes.extend({**node, "degree": degree.get(node["id"], 0)} for node in ghost_data.values())
        edge_rows = {(source, target): "wiki" for source, target in edges}
        for row in rows:
            target = row.target_document_id if row.target_document_id in visible else ghost_id(row.target_ref)
            if (row.source_document_id, target) in edge_rows:
                edge_rows[(row.source_document_id, target)] = row.link_type
        return {"nodes": nodes, "edges": [{"source": source, "target": target, "type": link_type} for (source, target), link_type in sorted(edge_rows.items())]}
    finally:
        session.close()
