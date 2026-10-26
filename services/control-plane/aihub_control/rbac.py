from sqlalchemy import exists, select
from sqlalchemy.orm import Session
from .models import Project, ProjectMember, User


def can_access_project(db: Session, user: User, project_id: str) -> bool:
    p = db.get(Project, project_id)
    return bool(
        user
        and (
            user.role == "admin"
            or (
                p
                and (
                    p.visibility in ("shared", "public")
                    or db.scalar(
                        select(
                            exists().where(
                                ProjectMember.user_id == user.id,
                                ProjectMember.project_id == project_id,
                            )
                        )
                    )
                )
            )
        )
    )
