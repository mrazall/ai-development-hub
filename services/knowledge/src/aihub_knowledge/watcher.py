from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from watchfiles import Change, awatch


async def watch_vault(root: Path, callback: Callable[[set[Path]], None], debounce_ms: int = 500) -> None:
    """Debounced watcher; callback receives paths and reconciliation handles deletes."""
    async for changes in awatch(root, debounce=debounce_ms):
        paths = {Path(path) for change, path in changes if change in (Change.modified, Change.added, Change.deleted)}
        await asyncio.to_thread(callback, paths)
