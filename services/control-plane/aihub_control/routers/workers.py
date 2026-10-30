import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..auth import current_principal, current_user, db_dep, hash_password, worker_principal, write_user
from ..deps import is_admin, mark_offline
from ..models import AgentEvent, Session, Worker, WorkerLease, WorkerToken
from ..schemas import FoundLoginsIn, HeartbeatIn, WorkerIn, WorkerOut

router = APIRouter(prefix="/workers", tags=["workers"])


@router.post("", response_model=WorkerOut)
def register_worker(data: WorkerIn, user=Depends(write_user), db=Depends(db_dep)):
    worker = db.get(Worker, data.id) or Worker(id=data.id)
    for key, value in data.model_dump().items():
        if key != "id":
            setattr(worker, key, value)
    worker.status = "online"
    worker.last_heartbeat_at = datetime.now(timezone.utc)
    worker = db.merge(worker)
    db.merge(
        WorkerLease(
            worker_id=worker.id,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=worker.lease_ttl_s),
        )
    )
    raw_token = secrets.token_urlsafe(32)
    db.add(WorkerToken(worker_id=worker.id, token_hash=hash_password(raw_token)))
    db.commit()
    db.refresh(worker)
    result = WorkerOut.model_validate(worker)
    result.worker_token = raw_token
    return result


@router.post("/{worker_id}/heartbeat", response_model=WorkerOut)
def heartbeat(
    worker_id: str,
    payload: HeartbeatIn | None = None,
    principal=Depends(current_principal),
    db=Depends(db_dep),
):
    if not is_admin(principal) and (
        not isinstance(principal, WorkerToken) or principal.worker_id != worker_id
    ):
        raise HTTPException(403, "worker token is not authorized for this worker")
    worker = db.get(Worker, worker_id)
    if not worker:
        raise HTTPException(404, "worker not found")
    worker.last_heartbeat_at = datetime.now(timezone.utc)
    worker.status = "online"
    lease = db.get(WorkerLease, worker_id)
    if lease:
        lease.expires_at = datetime.now(timezone.utc) + timedelta(seconds=worker.lease_ttl_s)
    else:
        db.add(
            WorkerLease(
                worker_id=worker_id,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=worker.lease_ttl_s),
            )
        )
    # A late heartbeat marks every session offline although the agents kept running; the worker
    # names the sessions it still runs, and those go back to running.
    active = (payload.active_sessions if payload else [])[:100]
    if active:
        for session in db.scalars(
            select(Session).where(Session.id.in_(active), Session.worker_id == worker_id, Session.status == "offline")
        ):
            session.status = "running"
            session.status_source = "heartbeat"
            db.add(AgentEvent(session_id=session.id, kind="session.status", source="heartbeat", payload={"status": "running"}))
    db.commit()
    return worker


@router.get("", response_model=list[WorkerOut])
def workers(user=Depends(current_user), db=Depends(db_dep)):
    mark_offline(db)
    active = dict(
        db.execute(
            select(Session.worker_id, func.count())
            .where(Session.status.in_({"starting", "running"}))
            .group_by(Session.worker_id)
        ).all()
    )
    return [
        WorkerOut.model_validate(worker).model_copy(update={"active_agents": active.get(worker.id, 0)})
        for worker in db.scalars(select(Worker))
    ]


@router.post("/{worker_id}/found-logins")
def found_logins(worker_id: str, data: FoundLoginsIn, worker=Depends(worker_principal), db=Depends(db_dep)):
    if worker.worker_id != worker_id:
        raise HTTPException(403, "worker token is not authorized for this worker")
    if any(item.engine not in {"claude", "codex"} for item in data.logins):
        raise HTTPException(422, "unsupported login engine")
    record = db.get(Worker, worker_id)
    if not record:
        raise HTTPException(404, "worker not found")
    record.found_logins = [item.model_dump() for item in data.logins]
    db.commit()
    return {"accepted": True}
