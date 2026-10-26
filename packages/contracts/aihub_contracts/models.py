"""Контракты v0.1. Источник истины для всех сервисов; JSON Schema генерируется из этих моделей.

Менять только оркестратору. Добавление необязательных полей — минорное изменение;
удаление/переименование — повышает API_VERSION и требует ADR.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "0.2"
SCHEMA_VERSION = 1


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Visibility(StrEnum):
    private = "private"  # только участники проекта
    shared = "shared"    # все пользователи хаба
    public = "public"    # можно экспортировать наружу


class Role(StrEnum):
    admin = "admin"
    viewer = "viewer"


class Engine(StrEnum):
    claude_code = "claude_code"
    codex = "codex"
    opencode = "opencode"
    gemini = "gemini"


class AuthMode(StrEnum):
    subscription = "subscription"  # официальный вход CLI
    api_key = "api_key"
    openrouter = "openrouter"
    local = "local"                # Ollama / OpenAI-compatible


class SessionStatus(StrEnum):
    queued = "queued"
    starting = "starting"
    running = "running"
    waiting_approval = "waiting_approval"
    blocked = "blocked"
    offline = "offline"
    failed = "failed"
    completed = "completed"


class StatusSource(StrEnum):
    native = "native"          # нативные события движка / хуки
    cli_parser = "cli_parser"  # разбор вывода терминала
    heartbeat = "heartbeat"    # только признак жизни


class TaskStatus(StrEnum):
    draft = "draft"
    ready = "ready"
    in_progress = "in_progress"
    review = "review"
    done = "done"
    cancelled = "cancelled"


class WorkerStatus(StrEnum):
    online = "online"
    offline = "offline"
    draining = "draining"


class WorkerKind(StrEnum):
    local = "local"
    ssh = "ssh"
    codeman = "codeman"


class DocType(StrEnum):
    overview = "overview"
    architecture = "architecture"
    decision = "decision"
    task = "task"
    handoff = "handoff"
    incident = "incident"
    runbook = "runbook"
    pattern = "pattern"
    research = "research"
    system = "system"


class DocStatus(StrEnum):
    active = "active"
    draft = "draft"
    deprecated = "deprecated"
    duplicate = "duplicate"


class BackupKind(StrEnum):
    vault = "vault"
    projects = "projects"
    db = "db"
    config = "config"
    sessions = "sessions"


class EventKind(StrEnum):
    session_status = "session.status"
    tool_call = "tool.call"
    tool_result = "tool.result"
    message = "message"
    output = "output"  # stdout/stderr, уже после redaction
    approval_request = "approval.request"
    approval_decision = "approval.decision"
    diff = "diff"
    test_result = "test.result"
    checkpoint = "checkpoint"
    handoff = "handoff"
    heartbeat = "heartbeat"


class Project(_Base):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str
    repo_url: str | None = None
    visibility: Visibility = Visibility.private
    allowed_paths: list[str] = []     # allowlist каталогов на worker
    allowed_commands: list[str] = []  # allowlist команд (glob)
    created_at: datetime
    updated_at: datetime


class Worker(_Base):
    id: str
    host: str  # tailscale-имя или адрес
    kind: WorkerKind
    status: WorkerStatus
    labels: list[str] = []  # gpu, wsl2, heavy ...
    last_heartbeat_at: datetime | None = None
    lease_ttl_s: int = 60


class Task(_Base):
    id: UUID
    project_id: str
    parent_id: UUID | None = None
    title: str
    body: str = ""
    status: TaskStatus = TaskStatus.draft
    depends_on: list[UUID] = []
    idempotency_key: str | None = None  # повторное создание с тем же ключом не порождает дубль
    created_at: datetime
    updated_at: datetime


class Session(_Base):
    id: UUID
    task_id: UUID | None = None
    project_id: str
    worker_id: str
    engine: Engine
    provider: str  # anthropic, openai, openrouter, ollama ...
    model: str
    auth_mode: AuthMode
    workdir: str
    branch: str | None = None
    status: SessionStatus = SessionStatus.queued
    status_source: StatusSource = StatusSource.heartbeat
    external_ref: str | None = None  # id сессии в Codeman / движке
    created_at: datetime
    updated_at: datetime


class AgentEvent(_Base):
    """Append-only. cursor — монотонный номер, назначает сервер; по нему replay после переподключения."""

    cursor: int | None = None
    schema_version: int = SCHEMA_VERSION
    session_id: UUID
    kind: EventKind
    source: StatusSource
    ts: datetime
    payload: dict[str, Any] = {}  # секреты вырезаются ДО записи
    redacted: bool = False


class KnowledgeDocument(_Base):
    """Frontmatter документа Vault (ТЗ 5.1)."""

    id: str
    project_id: str | None = None  # None — общий документ (02-Shared-Patterns, 03-Research)
    type: DocType
    title: str
    updated_at: datetime
    source: str  # human | agent:<engine> | import
    source_commit: str | None = None
    status: DocStatus = DocStatus.active
    visibility: Visibility = Visibility.private
    schema_version: int = SCHEMA_VERSION
    path: str  # относительный путь в Vault


class SearchHit(_Base):
    doc_id: str
    path: str
    title: str
    heading: str | None = None
    excerpt: str
    line_start: int
    line_end: int
    project_id: str | None
    updated_at: datetime
    score: float
    match: str = Field(pattern=r"^(lexical|vector|hybrid)$")


class Handoff(_Base):
    id: str
    project_id: str
    task_id: UUID | None = None
    from_session: UUID | None = None
    goal: str
    original_task: str
    done: list[str] = []
    decisions: list[str] = []
    changed_files: list[str] = []
    branch: str | None = None
    commit: str | None = None
    commands_and_tests: list[str] = []
    errors: list[str] = []
    risks: list[str] = []
    blockers: list[str] = []
    next_steps: list[str] = []
    sources: list[str] = []
    created_at: datetime


class BackupSnapshot(_Base):
    id: str    # restic snapshot id
    repo: str  # имя restic-репозитория, не URL с паролем
    kind: BackupKind
    started_at: datetime
    finished_at: datetime | None = None
    ok: bool
    size_bytes: int | None = None
    error: str | None = None
    tags: list[str] = []


# ---------------------------------------------------------------- v0.2 (ADR-002) — additive, backward compatible


class AccountKind(StrEnum):
    claude_code_subscription = "claude_code_subscription"  # official CLI login, isolated CLAUDE_CONFIG_DIR
    codex_subscription = "codex_subscription"              # official CLI login, isolated CODEX_HOME
    anthropic_api = "anthropic_api"
    openai_api = "openai_api"
    gemini_api = "gemini_api"
    openrouter = "openrouter"
    ollama = "ollama"
    openai_compatible = "openai_compatible"


class AccountStatus(StrEnum):
    pending_login = "pending_login"   # profile created, interactive official login not done yet
    connected = "connected"           # last check succeeded
    error = "error"                   # last check failed (see status_detail)
    disabled = "disabled"


class AccountProfile(_Base):
    """Metadata only. Secrets never live here: subscription auth stays in the profile's isolated config dir on the
    worker; API keys live in a worker-side secret file referenced by `secret_ref` (fingerprint for display)."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str
    kind: AccountKind
    worker_id: str                      # where the isolated config / secret file lives
    config_dir: str | None = None       # CLAUDE_CONFIG_DIR / CODEX_HOME for subscription kinds
    base_url: str | None = None         # ollama / openrouter / openai_compatible
    secret_ref: str | None = None       # path of the secret file on the worker (never the value)
    secret_fingerprint: str | None = None  # e.g. last 4 chars + sha256 prefix, for display only
    default_model: str | None = None
    models: list[str] = []
    status: AccountStatus = AccountStatus.pending_login
    status_detail: str | None = None
    checked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class McpTransport(StrEnum):
    stdio = "stdio"
    http = "http"


class McpServer(_Base):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str
    source: str              # package / repo URL
    version: str             # pinned
    license: str
    transport: McpTransport
    command: list[str] = []  # stdio launch command (no secrets inline)
    url: str | None = None
    scopes: list[str] = []   # e.g. "fs:read:/home/dev/projects/x", "db:read"
    project_ids: list[str] = []  # empty = available to no project until assigned
    enabled: bool = False
    status: str = "unknown"  # unknown | ok | error
    status_detail: str | None = None
    tools: list[str] = []


class NotificationSeverity(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class NotificationCategory(StrEnum):
    task_completed = "task.completed"
    agent_failed = "agent.failed"
    approval_required = "approval.required"
    worker_offline = "worker.offline"
    account_auth_failed = "account.auth_failed"
    backup_failed = "backup.failed"
    service_down = "service.down"


class Notification(_Base):
    id: UUID
    category: NotificationCategory
    severity: NotificationSeverity
    title: str
    body: str = ""            # no secrets, no code dumps
    project_id: str | None = None
    session_id: UUID | None = None
    link: str | None = None   # in-app route, e.g. /sessions/<id>
    created_at: datetime
    read_at: datetime | None = None


# Session additions (v0.2): parent_session_id builds the agent tree; account_profile_id picks the account;
# workspace_ref is the Codeman session id on the worker.
class SessionV2(Session):
    parent_session_id: UUID | None = None
    account_profile_id: str | None = None
    workspace_ref: str | None = None
    title: str | None = None


CONTRACT_MODELS = [
    Project, Task, Session, SessionV2, AgentEvent, Worker, KnowledgeDocument, Handoff, BackupSnapshot, SearchHit,
    AccountProfile, McpServer, Notification,
]
