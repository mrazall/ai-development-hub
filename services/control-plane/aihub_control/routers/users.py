from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..auth import db_dep, hash_password, write_user
from ..models import User
from ..schemas import UserIn, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(_admin=Depends(write_user), db=Depends(db_dep)):
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("", response_model=UserOut, status_code=201)
def create_user(data: UserIn, _admin=Depends(write_user), db=Depends(db_dep)):
    if data.role not in {"admin", "viewer"}:
        raise HTTPException(422, "role must be admin or viewer")
    if db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(409, "username already exists")
    user = User(username=data.username, password_hash=hash_password(data.password), role=data.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
