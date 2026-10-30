"""Parsers for official CLI rate-limit records; no credentials are inspected."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _find_rate_limits(value: Any, depth: int = 0) -> dict[str, Any] | None:
    """Real rollout files nest it: {"type":"event_msg","payload":{"type":"token_count","rate_limits":{...}}}."""
    if depth > 4:
        return None
    if isinstance(value, dict):
        if isinstance(value.get("rate_limits"), dict):
            return value["rate_limits"]
        for item in value.values():
            found = _find_rate_limits(item, depth + 1)
            if found is not None:
                return found
    return None


def parse_codex_rate_limits(lines: str) -> list[dict[str, Any]]:
    latest: dict[str, Any] | None = None
    for line in lines.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        limits = _find_rate_limits(value)
        if limits is not None:
            latest = limits
    if not latest:
        return []
    result = []
    for key, kind in (("primary", "five_hour"), ("secondary", "seven_day")):
        window = latest.get(key)
        if isinstance(window, dict) and isinstance(window.get("used_percent"), (int, float)):
            result.append({"kind": kind, "used_percent": float(window["used_percent"]), "resets_at": window.get("resets_at")})
    return result


def parse_codex_rate_limits_file(path: str | Path) -> list[dict[str, Any]]:
    try:
        return parse_codex_rate_limits(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return []


def latest_codex_rollout_rate_limits(
    codex_home: str | Path | None, started_at: float
) -> list[dict[str, Any]]:
    """Read only the newest rollout created during this worker session."""
    if not codex_home:
        return []
    root = Path(codex_home).expanduser()
    candidates = [
        path for path in root.glob("sessions/**/rollout-*.jsonl")
        if path.is_file() and path.stat().st_mtime >= started_at
    ]
    if not candidates:
        return []
    newest = max(candidates, key=lambda path: (path.stat().st_mtime, path))
    return parse_codex_rate_limits_file(newest)
