from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .models import SessionStatus


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class Login(BaseModel):
    username: str
    password: str


class ProjectIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str
    repo_url: str | None = None
    visibility: str = "private"
    allowed_paths: list[str] = []
    allowed_commands: list[str] = []


class ProjectOut(ProjectIn):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    deleted_at: datetime | None = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    session_id: str
    message_id: str | None
    original_name: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    expires_at: datetime | None
    sent_at: datetime | None


class DeletionImpact(BaseModel):
    tasks: int
    sessions: int
    active_sessions: int
    events: int
    attachments: int
    knowledge: int
    warning: str


class TaskIn(BaseModel):
    title: str
    body: str = ""
    status: str = "draft"
    idempotency_key: str | None = None
    parent_id: str | None = None
    depends_on: list[str] = []


class TaskOut(TaskIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime


class WorkerIn(BaseModel):
    id: str
    host: str
    kind: str
    labels: list[str] = []
    lease_ttl_s: int = 60


class HeartbeatIn(BaseModel):
    active_sessions: list[str] = []


class WorkerOut(WorkerIn):
    model_config = ConfigDict(from_attributes=True)
    status: str
    last_heartbeat_at: datetime | None
    worker_token: str | None = None


class PermissionRequestIn(BaseModel):
    """Claude Code's permission prompt for one tool call (from the hub MCP permission tool)."""
    tool_name: str = Field(min_length=1, max_length=255)
    input: dict[str, Any] = {}


class SessionIn(BaseModel):
    task_id: str | None = None
    # hold: created as a draft (not claimable) until POST /sessions/{id}/start — files are uploaded first.
    hold: bool = False
    project_id: str
    worker_id: str
    engine: str
    provider: str
    model: str
    auth_mode: str
    workdir: str
    branch: str | None = None
    parent_session_id: str | None = None
    account_profile_id: str | None = None
    workspace_ref: str | None = None
    title: str | None = None
    context_fresh: bool = False
    permission_mode: Literal["edits", "ask", "auto", "all"] = "edits"


class SessionOut(SessionIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    status_source: str
    created_at: datetime
    updated_at: datetime
    engine_session_ref: str | None = None
    context_tokens: int | None = None
    role: str | None = None
    orchestration: dict | None = None
    resume_at: datetime | None = None
    permission_mode: str = "edits"


# --- Orchestration ---
class OrchestratorProfileIn(BaseModel):
    account_profile_id: str = Field(min_length=1, max_length=63)
    model: str | None = Field(default=None, max_length=128)


class ExecutorProfileIn(BaseModel):
    count: int = Field(ge=1, le=4)
    account_profile_id: str = Field(min_length=1, max_length=63)
    model: str | None = Field(default=None, max_length=128)


class OrchestrationCreateIn(BaseModel):
    project_id: str = Field(min_length=1, max_length=63)
    title: str = Field(min_length=1, max_length=500)
    spec: str = Field(min_length=1, max_length=200_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    orchestrator: OrchestratorProfileIn
    executors: ExecutorProfileIn
    workdir: str | None = Field(default=None, max_length=1024)
    branch: str | None = Field(default=None, max_length=255)
    hold: bool = False
    # The orchestrator asks, the owner merges: executor branches are merged only after «Принять».
    manual_merge: bool = False


class PlanStepIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    status: str = Field(default="pending", pattern=r"^(pending|in_progress|done|blocked)$")
    executor_id: str | None = Field(default=None, max_length=36)


class PlanIn(BaseModel):
    steps: list[PlanStepIn] = Field(max_length=40)


class MergeRequestIn(BaseModel):
    summary: str = Field(default="", max_length=4000)


class MergeDecisionIn(BaseModel):
    reason: str = Field(default="", max_length=2000)


class ExecutorCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=1, max_length=200_000)
    reuse_branch_of: str | None = Field(default=None, max_length=36)


class ExecutorOut(BaseModel):
    id: str
    title: str | None
    status: str
    branch: str | None
    workdir: str
    last_message: str | None = None
    changed_files: list[str] = []
    started_at: datetime | None = None
    finished_at: datetime | None = None
    merge: dict | None = None


class ExecutorDetailOut(ExecutorOut):
    events: list[dict] = []


class ContinueIn(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    fresh: bool = False
    model: str | None = Field(default=None, max_length=128)
    # Claude Code --effort; None keeps what the session used before.
    effort: str | None = Field(default=None, pattern=r"^(low|medium|high|xhigh|max)$")
    # Claude Code permissions for the continuation; None keeps the session's mode.
    permission_mode: Literal["edits", "ask", "auto", "all"] | None = None


# --- Chats ---
class ChatCreateIn(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    model: str | None = Field(default=None, max_length=128)
    account_profile_id: str | None = Field(default=None, max_length=63)
    effort: str | None = Field(default=None, pattern=r"^(low|medium|high|xhigh|max)$")


class ChatPatchIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    pinned: bool | None = None


class ChatMessageOut(BaseModel):
    id: str | None = None
    role: str
    text: str
    created_at: datetime | None = None
    partial: bool = False
    tool_name: str | None = None
    tool_summary: str | None = None


class ChatOut(BaseModel):
    id: str
    title: str
    pinned: bool
    archived: bool = False
    session_id: str | None = None
    model: str | None = None
    account_profile_id: str | None = None
    effort: str | None = None
    updated_at: datetime
    created_at: datetime | None = None
    first_message: str | None = None
    status: str | None = None
    messages: list[ChatMessageOut] | None = None
    context: dict[str, int] | None = None


class StatusIn(BaseModel):
    status: SessionStatus


class EventIn(BaseModel):
    kind: str
    source: str = "native"
    ts: datetime | None = None
    payload: dict[str, Any] = {}
    client_event_id: str | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    cursor: int
    session_id: str
    kind: str
    source: str
    ts: datetime
    payload: dict[str, Any]
    redacted: bool = False

    @field_validator("redacted", mode="before")
    @classmethod
    def _redacted_default(cls, value: Any) -> bool:
        # Rows inserted outside the API may carry NULL; one such row must not break a whole history page.
        return bool(value)


class StreamTicket(BaseModel):
    ticket: str
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    role: str
    created_at: datetime


class UserIn(BaseModel):
    username: str
    password: str = Field(min_length=12)
    role: str = "viewer"


# --- Accounts & model connections ---
ACCOUNT_KINDS = {
    "claude_code_subscription", "codex_subscription", "anthropic_api", "openai_api",
    "gemini_api", "openrouter", "ollama", "openai_compatible",
}
ACCOUNT_STATUSES = {"pending_login", "connected", "error", "disabled"}


class AccountIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=255)
    kind: str
    worker_id: str = Field(min_length=1, max_length=128)
    base_url: str | None = None
    default_model: str | None = None
    models: list[str] = []


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    worker_id: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = None
    default_model: str | None = None
    models: list[str] | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    kind: str
    worker_id: str
    config_dir: str | None
    base_url: str | None
    secret_ref: str | None
    secret_fingerprint: str | None
    default_model: str | None
    models: list[str]
    status: str
    status_detail: str | None
    checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SecretIn(BaseModel):
    secret: str = Field(min_length=1)


class AccountStatusIn(BaseModel):
    status: str
    detail: str | None = None


# --- MCP registry ---
MCP_TRANSPORTS = {"stdio", "http", "sse"}


class McpIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=255)
    source: str
    version: str = Field(min_length=1, max_length=128)
    license: str = Field(min_length=1, max_length=128)
    transport: str
    command: list[str] = []
    url: str | None = None
    scopes: list[str] = []
    project_ids: list[str] = []
    enabled: bool = False
    status: str = "unknown"
    status_detail: str | None = None
    tools: list[str] = []


class McpPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    source: str | None = None
    version: str | None = Field(default=None, min_length=1, max_length=128)
    license: str | None = Field(default=None, min_length=1, max_length=128)
    transport: str | None = None
    command: list[str] | None = None
    url: str | None = None
    scopes: list[str] | None = None
    project_ids: list[str] | None = None
    status: str | None = None
    status_detail: str | None = None
    tools: list[str] | None = None


class McpOut(McpIn):
    model_config = ConfigDict(from_attributes=True)
    checked_at: datetime | None = None


class McpConfigOut(BaseModel):
    engine: str
    format: str
    config: str | dict


# --- Approvals ---
APPROVAL_STATUSES = {"pending", "approved", "rejected", "expired"}


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    worker_id: str
    action: str
    summary: str
    risk: str
    status: str
    requested_at: datetime
    expires_at: datetime | None
    decided_at: datetime | None
    decided_by: str | None


class ApprovalDecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")


# --- Backups ---
BACKUP_KINDS = {"database", "config", "vault", "projects", "restore_test"}


class BackupReportIn(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    repo: str = Field(min_length=1, max_length=255)
    kind: str
    started_at: datetime
    finished_at: datetime | None = None
    ok: bool
    size_bytes: int | None = Field(default=None, ge=0)
    error: str | None = Field(default=None, max_length=4000)
    tags: list[str] = []


class BackupSnapshotOut(BackupReportIn):
    model_config = ConfigDict(from_attributes=True)


class BackupStatusOut(BaseModel):
    kind: str
    last_success: BackupSnapshotOut | None
    age_seconds: float | None
    rpo_seconds: int | None
    rpo_exceeded: bool


# --- Account limits ---
class LimitWindowIn(BaseModel):
    kind: str = Field(pattern=r"^(five_hour|seven_day)$")
    used_percent: float = Field(ge=0, le=100)
    resets_at: int | None = None


class LimitsIn(BaseModel):
    captured_at: datetime
    windows: list[LimitWindowIn] = Field(max_length=2)
    status: str | None = Field(default=None, max_length=32)


class LimitWindowOut(BaseModel):
    kind: str
    used_percent: float
    resets_at: int | None
    captured_at: datetime
    stale: bool


class AccountLimitsOut(BaseModel):
    account_id: str
    account_name: str
    engine: str
    windows: list[LimitWindowOut]
