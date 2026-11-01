"""What agents read before they work — AGENTS.md, CLAUDE.md, skills — listed, read and edited from the panel.

Only a fixed set of Markdown files is reachable (see PROJECT_FILES / WORKER_FILES): paths come from the hub,
so the worker checks them itself, resolves links and refuses anything that lands outside its root.
Project files are committed (only that file); the worker's shared files get a backup before every write.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_BYTES = 256 * 1024
KEEP_BACKUPS = 20
SKILL = r"[a-z0-9][a-z0-9-]{0,63}"
# Project scope: paths relative to the project's working copy.
PROJECT_FILES = re.compile(rf"^(AGENTS\.md|CLAUDE\.md|\.claude/skills/{SKILL}/SKILL\.md)$")
# Worker scope: "claude/…" is ~/.claude and "codex/…" is ~/.codex — shared by the account profiles that link to
# them; "accounts/<id>/claude/…" or "accounts/<id>/codex/…" is a file of that profile alone.
_ENGINE_FILES = rf"(claude/CLAUDE\.md|claude/skills/{SKILL}/SKILL\.md|codex/AGENTS\.md)"
WORKER_FILES = re.compile(rf"^(accounts/{SKILL}/)?{_ENGINE_FILES}$")
READERS = {"AGENTS.md": ["codex"], "CLAUDE.md": ["claude"]}
COMMIT_AUTHOR = ["-c", "user.name=AI Hub panel", "-c", "user.email=panel@ai-dev-hub.local"]


class InstructionError(ValueError):
    """A request the worker refuses; the message is shown to the owner."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _readers(relative: str) -> list[str]:
    name = relative.rsplit("/", 1)[-1]
    return READERS.get(name, ["claude"])  # skills are Claude Code's


def _roots(home: Path) -> dict[str, Path]:
    return {"claude": home / ".claude", "codex": home / ".codex"}


def resolve(scope: str, relative: str, project_root: str | None, home: Path | None = None) -> tuple[Path, Path]:
    """The real file and the root it must stay in; refuses paths outside the allow-list or the root."""
    home = home or Path.home()
    if scope == "project":
        if not project_root or not PROJECT_FILES.match(relative):
            raise InstructionError("путь вне разрешённых: в проекте можно править AGENTS.md, CLAUDE.md и навыки")
        root = Path(project_root).expanduser()
        target = root / relative
    elif scope == "worker":
        if not WORKER_FILES.match(relative):
            raise InstructionError("путь вне разрешённых: на воркере можно править общие CLAUDE.md, навыки и AGENTS.md Codex")
        if relative.startswith("accounts/"):
            _, account, kind, rest = relative.split("/", 3)
            root = home / ".aihub" / "accounts" / account / kind
        else:
            kind, rest = relative.split("/", 1)
            root = _roots(home)[kind]
        target = root / rest
    else:
        raise InstructionError("неизвестная область")
    real_root = root.resolve()
    real = target.resolve()
    if real != real_root and real_root not in real.parents:
        raise InstructionError("путь ведёт за пределы разрешённой папки (через ссылку)")
    return real, real_root


def _profile_scope(home: Path, kind: str, inner: str) -> list[str]:
    """Accounts of an engine whose profile links `inner` (e.g. CLAUDE.md, skills) to the shared home dir."""
    shared = (_roots(home)[kind] / inner).resolve()
    accounts = []
    for profile in sorted((home / ".aihub" / "accounts").glob(f"*/{kind}")):
        candidate = profile / inner
        if (candidate.exists() or candidate.is_symlink()) and candidate.resolve() == shared:
            accounts.append(profile.parent.name)
    return accounts


def _entry(scope: str, relative: str, real: Path, home: Path) -> dict[str, Any]:
    exists = real.is_file()
    data = real.read_bytes() if exists else b""
    entry: dict[str, Any] = {
        "path": relative, "scope": scope, "readers": _readers(relative), "exists": exists,
        "size": len(data) if exists else None, "sha256": _sha(data) if exists else None,
        "updated_at": datetime.fromtimestamp(real.stat().st_mtime, UTC).isoformat() if exists else None,
        "skill": relative.split("/")[-2] if relative.endswith("/SKILL.md") else None,
    }
    if scope == "worker":
        if relative.startswith("accounts/"):
            entry["accounts"] = [relative.split("/")[1]]
        else:
            kind, rest = relative.split("/", 1)
            inner = rest if "/" not in rest else rest.split("/", 1)[0]
            entry["accounts"] = _profile_scope(home, kind, inner)
    return entry


def list_files(scope: str, project_root: str | None, home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    if scope == "project":
        root = Path(project_root or "").expanduser()
        if not project_root or not root.is_dir():
            raise InstructionError("папки проекта нет на этом воркере")
        names = ["AGENTS.md", "CLAUDE.md"]
        skills_dir = root / ".claude" / "skills"
        names += [f".claude/skills/{p.name}/SKILL.md" for p in sorted(skills_dir.glob("*")) if (p / "SKILL.md").is_file()]
        git = (root / ".git").exists()
    else:
        names = _worker_names(home)
        git = False
    files = []
    for relative in names:
        try:
            real, _ = resolve(scope, relative, project_root, home)
        except InstructionError:
            continue  # a link that leaves the root is not offered at all
        files.append(_entry(scope, relative, real, home))
    return {"files": files, "git": git}


def _worker_names(home: Path) -> list[str]:
    """Shared files, then each profile's own ones (a profile file that links to the shared one is not repeated)."""
    names = ["claude/CLAUDE.md", "codex/AGENTS.md"]
    names += [f"claude/skills/{p.name}/SKILL.md" for p in sorted((home / ".claude" / "skills").glob("*"))
              if (p / "SKILL.md").is_file()]
    for profile in sorted((home / ".aihub" / "accounts").glob("*/*")):
        kind, account = profile.name, profile.parent.name
        if kind not in ("claude", "codex") or not re.fullmatch(SKILL, account):
            continue
        own = ["CLAUDE.md"] if kind == "claude" else ["AGENTS.md"]
        if kind == "claude":
            own += [f"skills/{p.name}/SKILL.md" for p in sorted((profile / "skills").glob("*"))
                    if (p / "SKILL.md").is_file()]
        for inner in own:
            shared = (_roots(home)[kind] / inner).resolve()
            if (profile / inner).resolve() != shared:
                names.append(f"accounts/{account}/{kind}/{inner}")
    return names


def read_file(scope: str, relative: str, project_root: str | None, home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    real, _ = resolve(scope, relative, project_root, home)
    data = real.read_bytes() if real.is_file() else b""
    if len(data) > MAX_BYTES:
        raise InstructionError("файл больше 256 КБ — его не открыть в панели")
    return {**_entry(scope, relative, real, home), "content": data.decode("utf-8", errors="replace")}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *COMMIT_AUTHOR, *args], capture_output=True, text=True, timeout=30)


def _backup(home: Path, relative: str, real: Path) -> str | None:
    if not real.is_file():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    folder = home / ".aihub" / "backups" / "instructions" / relative.replace("/", "__")
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    shutil.copy2(real, folder / stamp)
    for old in sorted(folder.iterdir())[:-KEEP_BACKUPS]:
        old.unlink()
    return stamp


def write_file(scope: str, relative: str, content: str, base_sha256: str | None, project_root: str | None,
               home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    real, root = resolve(scope, relative, project_root, home)
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise InstructionError("файл больше 256 КБ")
    current = _sha(real.read_bytes()) if real.is_file() else None
    if current != (base_sha256 or None):
        raise InstructionError("conflict: файл изменился на воркере")
    result: dict[str, Any] = {"commit": None, "backup": None, "snapshot": None}
    if scope == "worker":
        result["backup"] = _backup(home, relative, real)
    elif (root / ".git").exists() and real.is_file():
        # The owner's own uncommitted edits of this file are kept in a commit of their own first.
        if _git(root, "status", "--porcelain", "--", relative).stdout.strip():
            _git(root, "add", "--", relative)
            _git(root, "commit", "-q", "-m", "snapshot: правки владельца перед правкой из панели", "--", relative)
            result["snapshot"] = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    real.parent.mkdir(parents=True, exist_ok=True)
    tmp = real.with_name(real.name + ".aihub-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, real)
    if scope == "project" and (root / ".git").exists():
        _git(root, "add", "--", relative)
        committed = _git(root, "commit", "-q", "-m", f"docs: инструкции агентов (из панели): {relative}", "--", relative)
        if committed.returncode == 0:
            result["commit"] = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    result["sha256"] = _sha(data)
    return result


def delete_skill(scope: str, relative: str, base_sha256: str | None, project_root: str | None,
                 home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    if not relative.endswith("/SKILL.md"):
        raise InstructionError("удалять можно только навыки")
    real, root = resolve(scope, relative, project_root, home)
    if not real.is_file():
        raise InstructionError("навыка уже нет")
    if _sha(real.read_bytes()) != base_sha256:
        raise InstructionError("conflict: файл изменился на воркере")
    result: dict[str, Any] = {"commit": None, "backup": None}
    if scope == "worker":
        result["backup"] = _backup(home, relative, real)
    real.unlink()
    try:
        real.parent.rmdir()
    except OSError:
        pass  # the skill folder holds other files: they stay
    if scope == "project" and (root / ".git").exists():
        _git(root, "add", "--", relative)
        if _git(root, "commit", "-q", "-m", f"docs: навык удалён из панели: {relative}", "--", relative).returncode == 0:
            result["commit"] = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return result


def list_backups(relative: str, home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    if not WORKER_FILES.match(relative):
        raise InstructionError("путь вне разрешённых")
    folder = home / ".aihub" / "backups" / "instructions" / relative.replace("/", "__")
    items = sorted(folder.iterdir(), reverse=True) if folder.is_dir() else []
    return {"backups": [{"id": item.name, "size": item.stat().st_size,
                         "content": item.read_text(encoding="utf-8", errors="replace")} for item in items]}


def restore_backup(relative: str, backup: str, base_sha256: str | None, home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    if not re.fullmatch(r"\d{8}T\d{12}Z", backup or ""):
        raise InstructionError("неизвестная резервная копия")
    source = home / ".aihub" / "backups" / "instructions" / relative.replace("/", "__") / backup
    if not source.is_file():
        raise InstructionError("резервной копии нет")
    return write_file("worker", relative, source.read_text(encoding="utf-8"), base_sha256, None, home)


def handle(params: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    """One instructions request from the hub: {op, scope, path?, content?, base_sha256?, project_root?, backup?}."""
    op, scope = params.get("op"), params.get("scope")
    path, root = params.get("path") or "", params.get("project_root")
    if op == "list":
        return list_files(scope, root, home)
    if op == "read":
        return read_file(scope, path, root, home)
    if op == "write":
        return write_file(scope, path, str(params.get("content") or ""), params.get("base_sha256"), root, home)
    if op == "delete":
        return delete_skill(scope, path, params.get("base_sha256"), root, home)
    if op == "backups" and scope == "worker":
        return list_backups(path, home)
    if op == "restore" and scope == "worker":
        return restore_backup(path, str(params.get("backup") or ""), params.get("base_sha256"), home)
    raise InstructionError("неизвестная операция")
