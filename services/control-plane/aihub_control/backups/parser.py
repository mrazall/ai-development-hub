"""Small, dependency-free parsers used by backup tests and reporting jobs."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def parse_restic_json(output: str) -> dict[str, Any]:
    """Return the last useful JSON object from restic's one-object-per-line output."""
    objects: list[dict[str, Any]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    if not objects:
        raise ValueError("restic output did not contain a JSON object")
    return objects[-1]


def rpo_exceeded(snapshot: Any, *, now, rpo_seconds: int) -> bool:
    """Check an aware snapshot timestamp against an RPO, treating missing data as failed."""
    if snapshot is None or not getattr(snapshot, "ok", False):
        return True
    finished = getattr(snapshot, "finished_at", None)
    return finished is None or (now - finished).total_seconds() > rpo_seconds


def latest_by_kind(snapshots: Iterable[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for snapshot in snapshots:
        current = result.get(snapshot.kind)
        if current is None or snapshot.started_at > current.started_at:
            result[snapshot.kind] = snapshot
    return result
