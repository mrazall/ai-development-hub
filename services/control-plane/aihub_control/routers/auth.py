from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..auth import current_user, db_dep, issue_token, verify_password
from ..config import Settings
from ..models import User
from ..schemas import Login, Token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(data: Login, db=Depends(db_dep)):
    user = db.scalar(select(User).where(User.username == data.username))
    if not user or not verify_password(user.password_hash, data.password):
        raise HTTPException(401, "invalid credentials")
    return issue_token(user, Settings())


@router.get("/me")
def me(user=Depends(current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}
