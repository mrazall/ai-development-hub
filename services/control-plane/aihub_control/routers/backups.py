from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select

from ..auth import current_user, db_dep
from ..models import BackupSnapshot
from ..orchestration.notifications import notify_users
from ..schemas import BACKUP_KINDS, BackupReportIn, BackupSnapshotOut, BackupStatusOut

router = APIRouter(prefix="/backups", tags=["backups"])
DATABASE_RPO_SECONDS = 6 * 60 * 60


def _configured_backup_token() -> str | None:
    token_file = os.environ.get("AIHUB_BACKUP_TOKEN_FILE")
    if token_file:
        try:
            value = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None
    return os.environ.get("AIHUB_BACKUP_TOKEN") or None


def backup_token(
    authorization: str | None = Header(default=None),
    x_backup_token: str | None = Header(default=None),
):
    configured = _configured_backup_token()
    supplied = x_backup_token
    if supplied is None and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not configured or not supplied or not hmac.compare_digest(
        hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(configured.encode()).digest()
    ):
        raise HTTPException(401, "backup authentication required")
    return True


@router.post("/report", response_model=BackupSnapshotOut, status_code=201)
def report_backup(
    data: BackupReportIn,
    _authorized=Depends(backup_token),
    db=Depends(db_dep),
):
    if data.kind not in BACKUP_KINDS:
        raise HTTPException(422, "unsupported backup kind")
    existing = db.get(BackupSnapshot, data.id)
    if existing:
        return existing
    snapshot = BackupSnapshot(**data.model_dump())
    db.add(snapshot)
    if not snapshot.ok:
        notify_users(
            db,
            "backup.failed",
            "Backup failed",
            f"The {snapshot.kind} backup reported an error.",
            severity="critical",
        )
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("", response_model=list[BackupSnapshotOut])
def list_backups(
    kind: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _user=Depends(current_user),
    db=Depends(db_dep),
):
    query = select(BackupSnapshot).order_by(BackupSnapshot.started_at.desc()).limit(limit)
    if kind:
        query = query.where(BackupSnapshot.kind == kind)
    return list(db.scalars(query))


@router.get("/status", response_model=list[BackupStatusOut])
def backup_status(_user=Depends(current_user), db=Depends(db_dep)):
    snapshots = list(db.scalars(select(BackupSnapshot).order_by(BackupSnapshot.started_at.desc())))
    kinds = sorted({item.kind for item in snapshots} | {"database"})
    now = datetime.now(timezone.utc)
    result = []
    for kind in kinds:
        successful = next((item for item in snapshots if item.kind == kind and item.ok), None)
        age = (now - successful.finished_at).total_seconds() if successful and successful.finished_at else None
        rpo = DATABASE_RPO_SECONDS if kind == "database" else None
        result.append(
            BackupStatusOut(
                kind=kind,
                last_success=successful,
                age_seconds=age,
                rpo_seconds=rpo,
                rpo_exceeded=successful is None or (rpo is not None and (age is None or age > rpo)),
            )
        )
    return result
