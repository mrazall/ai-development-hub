from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from ..auth import current_user, db_dep, write_user
from ..config import Settings
from ..deps import project_or_404
from ..models import AgentEvent, Attachment, Project, Session
from ..schemas import AttachmentOut

router = APIRouter(tags=["attachments"])
MAX_BYTES = 20 * 1024 * 1024
MAX_PER_MESSAGE = 10
_SAFE_NAME = re.compile(r"[^\w .()\[\]-]+", re.UNICODE)
_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".kt", ".sh", ".sql", ".yaml", ".yml", ".toml", ".ini", ".css", ".html", ".xml", ".txt", ".md", ".json", ".csv", ".pdf"}
_MIME = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain", "text/markdown", "application/json", "text/csv"}


def safe_filename(name: str) -> str:
    value = Path(name or "attachment").name.replace("..", "")
    value = _SAFE_NAME.sub("_", value).strip(" .")[:200]
    return value or "attachment"


def _valid_signature(mime: str, data: bytes) -> bool:
    return (
        (mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
        or (mime == "image/gif" and data[:6] in (b"GIF87a", b"GIF89a"))
        or (mime == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
        or (mime == "application/pdf" and data.startswith(b"%PDF-"))
        or (mime in {"text/plain", "text/markdown", "text/csv", "application/json"} and b"\x00" not in data[:4096])
    )


def _storage_root() -> Path:
    root = Path(Settings().data_dir).expanduser().resolve() / "attachments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_for_user(db, user, session_id: str) -> Session:
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    project_or_404(db, user, session.project_id)
    return session


@router.post("/sessions/{session_id}/attachments", response_model=AttachmentOut, status_code=201)
def upload_attachment(
    session_id: str,
    file: UploadFile = File(...),
    message_id: str | None = Form(default=None),
    user=Depends(write_user),
    db=Depends(db_dep),
):
    session = _session_for_user(db, user, session_id)
    mime = (file.content_type or "").lower().split(";", 1)[0]
    suffix = Path(file.filename or "").suffix.lower()
    if mime not in _MIME or (mime.startswith("image/") and suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}) or (not mime.startswith("image/") and suffix not in _EXTENSIONS):
        raise HTTPException(415, "unsupported attachment type")
    pending = db.scalar(select(func.count(Attachment.id)).where(Attachment.session_id == session_id, Attachment.sent_at.is_(None)))
    if pending >= MAX_PER_MESSAGE:
        raise HTTPException(413, "maximum 10 pending attachments per message")
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "attachment exceeds 20 MiB")
    if not _valid_signature(mime, data):
        raise HTTPException(415, "attachment signature does not match its MIME type")
    attachment_id = str(uuid4())
    path = _storage_root() / attachment_id
    path.write_bytes(data)
    attachment = Attachment(
        id=attachment_id, project_id=session.project_id, session_id=session_id,
        message_id=message_id, original_name=safe_filename(file.filename or "attachment"),
        mime_type=mime, size_bytes=len(data), storage_path=str(path), uploaded_by=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/sessions/{session_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(session_id: str, user=Depends(current_user), db=Depends(db_dep)):
    _session_for_user(db, user, session_id)
    return list(db.scalars(select(Attachment).where(Attachment.session_id == session_id).order_by(Attachment.created_at)))


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: str, user=Depends(current_user), db=Depends(db_dep)):
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(404, "attachment not found")
    _session_for_user(db, user, attachment.session_id)
    path = Path(attachment.storage_path).resolve()
    if not path.is_file() or path.parent != _storage_root().resolve():
        raise HTTPException(404, "attachment content not found")
    return FileResponse(path, media_type=attachment.mime_type, filename=attachment.original_name)


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: str, user=Depends(write_user), db=Depends(db_dep)):
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(404, "attachment not found")
    _session_for_user(db, user, attachment.session_id)
    if attachment.sent_at:
        raise HTTPException(409, "sent attachments cannot be deleted")
    Path(attachment.storage_path).unlink(missing_ok=True)
    db.delete(attachment)
    db.commit()
