"""The panel's file browser: list and read files of a session's working folder, never outside it.

The hub queues a request; the worker answers with a listing or one file (base64, up to MAX_BYTES). Paths are
relative to the session's workdir and checked after resolving links, like the instructions editor.
"""
from __future__ import annotations

import base64
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 2000
# Where agents leave files for the owner (screenshots, reports): the panel shows it first.
SHARE_DIR = ".aihub/share"
_HIDDEN = {".git", "node_modules", "__pycache__", ".venv", ".pytest_cache"}


class FilesError(ValueError):
    pass


def _resolve(root: Path, relative: str) -> Path:
    if "\x00" in relative or relative.startswith("\\"):
        raise FilesError("путь вне рабочей папки")
    # An absolute path from an agent's answer is fine when it lies inside the folder; the check below holds.
    target = (Path(relative) if relative.startswith("/") else root / relative).resolve()
    if target != root and root not in target.parents:
        raise FilesError("путь вне рабочей папки")
    return target


def _stamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def list_dir(root: Path, relative: str = "") -> dict:
    folder = _resolve(root, relative)
    if not folder.is_dir():
        raise FilesError("папки нет")
    entries = []
    for entry in sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if entry.name in _HIDDEN:
            continue
        try:
            resolved = entry.resolve()
            if resolved != root and root not in resolved.parents:
                continue  # a link out of the workdir is not offered
            is_dir = entry.is_dir()
            entries.append({"name": entry.name, "path": str(entry.relative_to(root)), "dir": is_dir,
                            "size": None if is_dir else entry.stat().st_size, "updated_at": _stamp(entry)})
        except OSError:
            continue
        if len(entries) >= MAX_ENTRIES:
            break
    return {"path": "" if folder == root else str(folder.relative_to(root)), "entries": entries,
            "share": SHARE_DIR if (root / SHARE_DIR).is_dir() else None}


def read_file(root: Path, relative: str) -> dict:
    target = _resolve(root, relative)
    if not target.is_file():
        raise FilesError("файла нет")
    size = target.stat().st_size
    if size > MAX_BYTES:
        raise FilesError(f"файл больше {MAX_BYTES // (1024 * 1024)} МБ")
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return {"path": relative, "size": size, "mime": mime, "updated_at": _stamp(target),
            "base64": base64.b64encode(target.read_bytes()).decode("ascii")}


def handle(params: dict) -> dict:
    workdir = params.get("workdir")
    if not workdir:
        raise FilesError("у сессии нет рабочей папки")
    root = Path(os.path.expanduser(str(workdir))).resolve()
    if not root.is_dir():
        raise FilesError("рабочей папки нет на воркере")
    op, path = params.get("op"), str(params.get("path") or "")
    if op == "list":
        return list_dir(root, path)
    if op == "read":
        return read_file(root, path)
    raise FilesError("неизвестная операция")
