from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..auth import current_user, db_dep, worker_principal
from ..models import AccountLimit, AccountProfile, WorkerRequest, WorkerToken
from ..schemas import AccountLimitsOut, LimitsIn

router = APIRouter(prefix="/limits", tags=["limits"])
accounts_router = APIRouter(prefix="/accounts", tags=["limits"])


def _stale(captured_at: datetime) -> bool:
    return captured_at < datetime.now(timezone.utc) - timedelta(hours=6)


@router.get("", response_model=list[AccountLimitsOut])
def list_limits(_user=Depends(current_user), db=Depends(db_dep)):
    accounts = list(db.scalars(select(AccountProfile).order_by(AccountProfile.name)))
    result = []
    for account in accounts:
        rows = list(db.scalars(select(AccountLimit).where(AccountLimit.account_id == account.id)))
        result.append(AccountLimitsOut(account_id=account.id, account_name=account.name, engine=account.kind, windows=[
            {"kind": row.kind, "used_percent": row.used_percent, "resets_at": row.resets_at,
             "captured_at": row.captured_at, "stale": _stale(row.captured_at)} for row in rows
        ]))
    return result


@accounts_router.post("/{account_id}/limits", status_code=204)
def capture_limits(account_id: str, data: LimitsIn, worker=Depends(worker_principal), db=Depends(db_dep)):
    account = db.get(AccountProfile, account_id)
    if not account:
        raise HTTPException(404, "account not found")
    if not isinstance(worker, WorkerToken) or worker.worker_id != account.worker_id:
        raise HTTPException(403, "worker token is not authorized for this account")
    for item in data.windows:
        row = db.scalar(select(AccountLimit).where(AccountLimit.account_id == account_id, AccountLimit.kind == item.kind))
        if row is None:
            row = AccountLimit(account_id=account_id, kind=item.kind)
            db.add(row)
        row.used_percent, row.resets_at, row.captured_at, row.status = item.used_percent, item.resets_at, data.captured_at, data.status
    db.commit()


@accounts_router.post("/{account_id}/limits/refresh")
def refresh_limits(account_id: str, _user=Depends(current_user), db=Depends(db_dep)):
    account = db.get(AccountProfile, account_id)
    if not account:
        raise HTTPException(404, "account not found")
    request = WorkerRequest(worker_id=account.worker_id, kind="limits_refresh", response={"account_id": account.id, "kind": account.kind})
    db.add(request)
    db.commit()
    return {"queued": True, "request_id": request.id, "warning": "Обновление тратит немного лимита"}
