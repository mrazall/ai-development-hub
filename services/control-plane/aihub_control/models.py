from typing import Any
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Float,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(timezone.utc)


class Role(StrEnum):
    admin = "admin"
    viewer = "viewer"


class Visibility(StrEnum):
    private = "private"
    shared = "shared"
    public = "public"


class WorkerStatus(StrEnum):
    online = "online"
    offline = "offline"
    draining = "draining"


class SessionStatus(StrEnum):
    queued = "queued"
    starting = "starting"
    running = "running"
    waiting_approval = "waiting_approval"
    blocked = "blocked"
    offline = "offline"
    failed = "failed"
    completed = "completed"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default=Role.viewer.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)



class DeviceSession(Base):
    """A signed-in browser or app. Only a hash of its refresh token is stored."""

    __tablename__ = "device_sessions"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("control.users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # The token before the last rotation, accepted briefly so two tabs refreshing at once both stay signed in.
    previous_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(63), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    repo_url: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.private.value)
    allowed_paths: Mapped[list] = mapped_column(JSON, default=list)
    allowed_commands: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # --- Personal chats ---
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = {"schema": "control"}
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("control.users.id"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("control.projects.id"), primary_key=True
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "idempotency_key"), {"schema": "control"})
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(63), ForeignKey("control.projects.id"), index=True
    )
    parent_id: Mapped[str | None] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default=WorkerStatus.online.value)
    labels: Mapped[list] = mapped_column(JSON, default=list)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_ttl_s: Mapped[int] = mapped_column(Integer, default=60)
    found_logins: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class WorkerLease(Base):
    __tablename__ = "worker_leases"
    __table_args__ = {"schema": "control"}
    worker_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("control.workers.id"), primary_key=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkerToken(Base):
    __tablename__ = "worker_tokens"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    worker_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("control.workers.id"), index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str | None] = mapped_column(String(36))
    project_id: Mapped[str] = mapped_column(String(63), ForeignKey("control.projects.id"))
    worker_id: Mapped[str] = mapped_column(String(128))
    engine: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    auth_mode: Mapped[str] = mapped_column(String(32))
    workdir: Mapped[str] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default=SessionStatus.queued.value)
    status_source: Mapped[str] = mapped_column(String(32), default="heartbeat")
    external_ref: Mapped[str | None] = mapped_column(String(255))
    # --- Claude continuation ---
    engine_session_ref: Mapped[str | None] = mapped_column(String(255))
    context_tokens: Mapped[int | None] = mapped_column(Integer)
    context_fresh: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parent_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    account_profile_id: Mapped[str | None] = mapped_column(String(36))
    workspace_ref: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(500))
    # --- Orchestration ---
    role: Mapped[str | None] = mapped_column(String(16))
    orchestration: Mapped[dict | None] = mapped_column(JSON)
    # --- Personal chats ---
    chat_id: Mapped[str | None] = mapped_column(String(36), index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mcp_config: Mapped[dict | None] = mapped_column(JSON)
    # Set when a provider limit stopped the session: the hub continues it at this moment.
    resume_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Claude Code permissions: edits (file edits only), ask (the owner approves each other action in the panel),
    # auto (Claude's auto mode: a classifier allows routine actions, blocks risky ones), all (bypassPermissions).
    permission_mode: Mapped[str] = mapped_column(String(16), default="edits", server_default="edits", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    # The owner looked at a failed session and marked it «всё ок»; the panel stops showing it red.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = {"schema": "control"}
    cursor: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    client_event_id: Mapped[str | None] = mapped_column(String(255))
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "control"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str | None] = mapped_column(String(255))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


# --- Accounts & model connections ---
class AccountProfile(Base):
    __tablename__ = "account_profiles"
    __table_args__ = {"schema": "control"}

    id: Mapped[str] = mapped_column(String(63), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    config_dir: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text)
    secret_ref: Mapped[str | None] = mapped_column(Text)
    secret_fingerprint: Mapped[str | None] = mapped_column(String(64))
    default_model: Mapped[str | None] = mapped_column(String(255))
    models: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending_login", nullable=False)
    status_detail: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identity: Mapped[str | None] = mapped_column(String(255))
    identity_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    login_watch_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    session_id: Mapped[str | None] = mapped_column(String(36))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkerRequest(Base):
    __tablename__ = "worker_requests"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    worker_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- MCP registry ---
class McpServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = {"schema": "control"}

    id: Mapped[str] = mapped_column(String(63), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    license: Mapped[str] = mapped_column(String(128), nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False)
    command: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    project_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    status_detail: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tools: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


# --- Worker capability snapshots ---
class WorkerCapability(Base):
    __tablename__ = "worker_capabilities"
    __table_args__ = {"schema": "control"}
    worker_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("control.workers.id"), primary_key=True
    )
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    workspace_url: Mapped[str | None] = mapped_column(Text)
    # How to open a terminal on this worker ("wsl -d Ubuntu -u dev", "ssh -t dev@host"), as it reports it.
    shell_hint: Mapped[str | None] = mapped_column(Text)
    # {"codex": [{"slug", "name", "efforts", "default_effort"}]} — what the worker's CLIs offer.
    models: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


# --- Approvals ---
class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = {"schema": "control"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("control.sessions.id"), index=True)
    worker_id: Mapped[str] = mapped_column(String(128), ForeignKey("control.workers.id"), index=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(36))


# --- Attachments and project lifecycle ---
class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(63), ForeignKey("control.projects.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("control.sessions.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(Text, unique=True)
    uploaded_by: Mapped[str] = mapped_column(String(36), ForeignKey("control.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectLifecycleError(Base):
    __tablename__ = "project_lifecycle_errors"
    __table_args__ = {"schema": "control"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(63), index=True)
    operation: Mapped[str] = mapped_column(String(32))
    error: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# --- Account limits ---
class AccountLimit(Base):
    __tablename__ = "account_limits"
    __table_args__ = (UniqueConstraint("account_id", "kind"), {"schema": "control"})
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    account_id: Mapped[str] = mapped_column(String(63), ForeignKey("control.account_profiles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    used_percent: Mapped[float] = mapped_column(Float)
    resets_at: Mapped[int | None] = mapped_column(BigInteger)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str | None] = mapped_column(String(32))


# --- Backups ---
class BackupSnapshot(Base):
    __tablename__ = "backup_snapshots"
    __table_args__ = {"schema": "control"}

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    repo: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


# --- Settings changed in the panel (override the deployment env) ---
class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = {"schema": "control"}
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


@event.listens_for(Session.status, "set")
def _status_changed(target, value, oldvalue, _initiator):
    if value != oldvalue:
        target.acknowledged_at = None


# --- efficiency: execution runs ---
class ExecutionRun(Base):
    __tablename__ = "execution_runs"
    __table_args__ = (UniqueConstraint("session_id", "run_index"), {"schema": "control"})
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(63), index=True)
    run_index: Mapped[int] = mapped_column(Integer)
    external_run_id: Mapped[str | None] = mapped_column(String(64))
    engine: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    account_profile_id: Mapped[str | None] = mapped_column(String(36))
    role: Mapped[str | None] = mapped_column(String(16))
    orchestration_id: Mapped[str | None] = mapped_column(String(36))
    trigger: Mapped[str] = mapped_column(String(24))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str] = mapped_column(String(16))
    waiting_approval_s: Mapped[float | None] = mapped_column(Float)
    waiting_limit_s: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
