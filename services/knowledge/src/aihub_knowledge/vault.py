from __future__ import annotations

import os

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REQUIRED = {"id", "type", "title", "updated_at", "source", "status", "visibility", "schema_version"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)\b(?:api[_ -]?key|secret|token|password)\s*[:=]\s*['\"]?[^\s'\"]{12,}"),
    re.compile(r"(?i)\b(?:vless|vmess|ss|trojan)://[^\s]+"),
    re.compile(r"\btskey-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?im)^\s*authorization:\s*bearer\s+[A-Za-z0-9._~+/=-]{20,}\s*$"),
)
EXCLUDED_NAMES = {"node_modules", ".obsidian", ".git", ".trash", "_Агенты"}
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".db", ".sqlite"}


@dataclass(frozen=True)
class VaultError:
    path: str
    reason: str


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    project_id: str | None
    type: str
    title: str
    updated_at: datetime
    source: str
    source_commit: str | None
    status: str
    visibility: str
    schema_version: int
    path: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class ParsedVault:
    document: KnowledgeDocument | None
    errors: tuple[VaultError, ...] = ()


def _excluded(path: Path, root: Path, ignored: set[str]) -> bool:
    rel = path.relative_to(root)
    return any(part in EXCLUDED_NAMES or part in ignored for part in rel.parts) or any(
        part.startswith((".env", "id_")) or part.endswith(".pem") for part in rel.parts
    )


def _has_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


_EMOJI_PREFIX = re.compile(
    r"^(?:(?:[\U0001F300-\U0001FAFF\u2600-\u27BF])(?:\ufe0f|[\U0001F3FB-\U0001F3FF])?(?:\u200d(?:[\U0001F300-\U0001FAFF\u2600-\u27BF])(?:\ufe0f|[\U0001F3FB-\U0001F3FF])?)*\s*)+"
)


def _title_from_content(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            title = _EMOJI_PREFIX.sub("", line[2:]).strip()
            if title:
                return title
            break
    return fallback


def _derived_metadata(path: Path, root: Path, content: str) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {
        # Prefix of ids for notes without frontmatter; keep it stable per deployment (ids are referenced).
        "id": f"{os.environ.get('AIHUB_VAULT_ID_PREFIX', 'vault')}:{relative}",
        "project_id": None,
        "type": "note",
        "title": _title_from_content(content, path.stem),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
        "source": "vault",
        "source_commit": None,
        "status": "active",
        "visibility": "private",
        "schema_version": 1,
    }


def parse_markdown(path: Path, root: Path) -> ParsedVault:
    relative = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ParsedVault(None, (VaultError(relative, f"read error: {exc}"),))
    if _has_secret(text):
        return ParsedVault(None, (VaultError(relative, "secret detected; document was not indexed"),))
    metadata = _derived_metadata(path, root, text)
    content = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end < 0:
            return ParsedVault(None, (VaultError(relative, "unterminated YAML frontmatter"),))
        try:
            frontmatter = yaml.safe_load(text[4:end]) or {}
        except yaml.YAMLError as exc:
            return ParsedVault(None, (VaultError(relative, f"invalid YAML: {exc}"),))
        if not isinstance(frontmatter, dict):
            return ParsedVault(None, (VaultError(relative, "invalid frontmatter: expected a mapping"),))
        metadata.update(frontmatter)
        content = text[end + 4 :].lstrip("\n")
    try:
        updated = metadata["updated_at"]
        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        document = KnowledgeDocument(
            id=str(metadata["id"]),
            project_id=metadata.get("project_id"),
            type=str(metadata["type"]),
            title=str(metadata["title"]),
            updated_at=updated,
            source=str(metadata["source"]),
            source_commit=metadata.get("source_commit"),
            status=str(metadata["status"]),
            visibility=str(metadata["visibility"]),
            schema_version=int(metadata["schema_version"]),
            path=relative,
            content=content,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
    except (TypeError, ValueError, KeyError) as exc:
        return ParsedVault(None, (VaultError(relative, f"invalid frontmatter: {exc}"),))
    return ParsedVault(document)


def scan_vault(root: Path) -> tuple[list[KnowledgeDocument], list[VaultError]]:
    ignored = set()
    ignore_file = root / ".aihubignore"
    if ignore_file.exists():
        ignored = {
            line.strip() for line in ignore_file.read_text().splitlines() if line.strip() and not line.startswith("#")
        }
    documents: list[KnowledgeDocument] = []
    errors: list[VaultError] = []
    if not root.exists():
        return [], [VaultError(".", "vault directory does not exist")]
    for path in sorted(root.rglob("*.md")):
        if _excluded(path, root, ignored):
            continue
        parsed = parse_markdown(path, root)
        if parsed.document:
            documents.append(parsed.document)
        errors.extend(parsed.errors)
    return documents, errors
