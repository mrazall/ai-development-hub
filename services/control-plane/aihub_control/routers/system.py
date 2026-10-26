from fastapi import APIRouter, Body, Depends

from ..auth import current_user, db_dep, write_user
from ..health import collect
from ..system_settings import describe, get_setting, reset, save

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info")
def system_info(_user=Depends(current_user), db=Depends(db_dep)):
    """What the panel needs to know about this deployment."""
    from .. import API_VERSION
    from ..config import Settings

    return {"demo": Settings().demo, "version": API_VERSION, "obsidian_vault": get_setting(db, "obsidian_vault")}


@router.get("/health")
def system_health(_user=Depends(current_user), db=Depends(db_dep)):
    return collect(db)


@router.get("/settings")
def list_settings(_admin=Depends(write_user), db=Depends(db_dep)):
    return describe(db)


@router.put("/settings/{key}")
def change_setting(key: str, value=Body(..., embed=True), admin=Depends(write_user), db=Depends(db_dep)):
    save(db, key, value, admin.username)
    return describe(db)


@router.delete("/settings/{key}")
def reset_setting(key: str, _admin=Depends(write_user), db=Depends(db_dep)):
    reset(db, key)
    return describe(db)
