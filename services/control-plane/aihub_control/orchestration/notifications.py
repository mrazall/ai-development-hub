from datetime import datetime, timezone

from sqlalchemy import select

from ..models import Notification, User


def notify(db, category: str, title: str, body: str = "", *, severity: str = "info", user_id: str | None = None, session_id: str | None = None):
    notification = Notification(user_id=user_id, category=category, severity=severity, title=title, body=body, session_id=session_id)
    db.add(notification)
    db.flush()
    return notification


def notify_users(db, category: str, title: str, body: str = "", **kwargs):
    users = db.scalars(select(User)).all()
    return [notify(db, category, title, body, user_id=user.id, **kwargs) for user in users]
