import argparse
import getpass
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .auth import hash_password
from .db import SessionLocal
from .models import AccountProfile, Project, SystemSetting, User, Worker, WorkerLease, WorkerToken


def demo_seed(token_file: str) -> None:
    """Quickstart demo: a worker with mock engines, a project, two profiles and chats on the mock engine.

    Idempotent; writes a fresh worker token to `token_file` (a volume shared with the demo worker).
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        worker = db.get(Worker, "demo-worker") or Worker(id="demo-worker", host="demo-worker", kind="linux")
        worker.status, worker.last_heartbeat_at, worker.labels = "online", now, ["demo"]
        worker = db.merge(worker)
        db.merge(WorkerLease(worker_id=worker.id, expires_at=now + timedelta(seconds=worker.lease_ttl_s or 60)))
        raw = secrets.token_urlsafe(32)
        db.add(WorkerToken(worker_id=worker.id, token_hash=hash_password(raw)))
        if not db.get(Project, "demo"):
            db.add(Project(id="demo", name="Demo project", visibility="shared", allowed_paths=["/work/demo"]))
        for profile_id, name, kind in (
            ("demo-claude", "Demo Claude (mock)", "claude_code_subscription"),
            ("demo-codex", "Demo Codex (mock)", "codex_subscription"),
        ):
            if not db.get(AccountProfile, profile_id):
                db.add(AccountProfile(id=profile_id, name=name, kind=kind, worker_id=worker.id,
                                      config_dir=f"/work/.{profile_id}", models=[],
                                      # Mock engines need no login: the profiles are usable as they are.
                                      status="connected"))
        # Chats answer with the mock engine (repeats the question) — no subscription needed.
        setting = db.get(SystemSetting, "chat_engine") or SystemSetting(key="chat_engine")
        setting.value, setting.updated_by, setting.updated_at = "mock_echo_prompt", "demo-seed", now
        db.merge(setting)
        db.commit()
        path = Path(token_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        path.chmod(0o600)
        print("demo seeded: worker demo-worker, project demo, chats on the mock engine")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin")
    p.add_argument("--username", default="admin")
    sub.add_parser("purge")
    d = sub.add_parser("demo-seed")
    d.add_argument("--worker-token-file", default="/shared/worker-token")
    args = parser.parse_args()
    if args.command == "create-admin":
        password = os.environ.get("AIHUB_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
        db = SessionLocal()
        if db.query(User).filter_by(username=args.username).first():
            print(f"admin {args.username} exists")
            return
        db.add(User(username=args.username, password_hash=hash_password(password), role="admin"))
        db.commit()
        print(f"created admin {args.username}")
    elif args.command == "purge":
        from .orchestration.lifecycle import purge_expired

        db = SessionLocal()
        try:
            print(purge_expired(db))
        finally:
            db.close()
    elif args.command == "demo-seed":
        demo_seed(args.worker_token_file)
