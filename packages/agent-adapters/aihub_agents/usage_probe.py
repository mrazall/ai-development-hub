"""Subscription limits without spending them: the CLI's own `/usage` (Claude Code) or `/status` (Codex).

The official CLI runs in a pseudo-terminal with the account's profile, the slash command is typed, the screen is
rendered with pyte and read back. Nothing is sent to the model, no token is read or used outside the CLI.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import re
import select
import shutil
import struct
import termios
import time
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pyte

COLS, ROWS = 120, 50
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _screen_text(screen: pyte.Screen) -> str:
    return "\n".join(line.rstrip() for line in screen.display if line.strip())


def read_slash_command(argv: list[str], env: dict[str, str], command: str, workdir: Path,
                       timeout: float = 40.0) -> str:
    """Start the CLI (*argv*) in a pseudo-terminal, type *command*, return the rendered screen, quit the CLI."""
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)
    workdir.mkdir(parents=True, exist_ok=True)
    pid, fd = pty.fork()
    if pid == 0:  # child: the CLI itself
        os.chdir(workdir)
        os.execvpe(argv[0], argv, {**env, "TERM": "xterm-256color",
                                              "COLUMNS": str(COLS), "LINES": str(ROWS)})
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    deadline = time.monotonic() + timeout

    def pump(seconds: float, until: str | None = None) -> None:
        end = min(time.monotonic() + seconds, deadline)
        while time.monotonic() < end:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                if until and until in _screen_text(screen):
                    return
                continue
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                return
            if not chunk:
                return
            stream.feed(chunk)
            if b"\x1b[6n" in chunk:  # cursor position query: TUIs wait for the answer
                os.write(fd, f"\x1b[{screen.cursor.y + 1};{screen.cursor.x + 1}R".encode())

    try:
        pump(10, until="? for shortcuts")
        if "trust this folder" in _screen_text(screen):
            # The probe's own empty folder: confirm "Yes, I trust this folder" once.
            if "❯ Yes" not in _screen_text(screen):
                os.write(fd, b"\x1b[B")
                time.sleep(0.3)
            os.write(fd, b"\r")
            pump(8, until="? for shortcuts")
        for char in command:
            os.write(fd, char.encode())
            time.sleep(0.03)
        pump(0.8)
        os.write(fd, b"\r")
        pump(10, until="% ")
        pump(1.5)
        return _screen_text(screen)
    finally:
        for key in (b"\x1b", b"\x03", b"\x03"):
            try:
                os.write(fd, key)
            except OSError:
                break
            time.sleep(0.2)
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        os.close(fd)


def _local_zone() -> tzinfo:
    name = os.environ.get("TZ", "")
    if not name:
        try:
            name = os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
        except IndexError:
            name = ""
    try:
        return ZoneInfo(name) if name else datetime.now().astimezone().tzinfo  # type: ignore[return-value]
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def parse_reset(text: str, now: datetime) -> int | None:
    """'5:49pm', '7pm', '21:52', 'Nov 4, 7:59pm', '12:31 PM on 4 Nov' (optionally '(Europe/Moscow)') → epoch."""
    zone = now.tzinfo
    named = re.search(r"\(([A-Za-z_]+/[A-Za-z_/+-]+)\)", text)
    if named:
        try:
            zone = ZoneInfo(named.group(1))
        except ZoneInfoNotFoundError:
            pass
    now = now.astimezone(zone)
    clock = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b", text, re.I)
    if clock:
        hour = int(clock.group(1)) % 12 + (12 if clock.group(3).lower() == "p" else 0)
        minute = int(clock.group(2) or 0)
    else:  # a 24-hour locale: "21:52", "12:31 on 4 Nov"
        clock = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
        if not clock:
            return None
        hour, minute = int(clock.group(1)), int(clock.group(2))
    day = re.search(r"\b([A-Za-z]{3})[a-z]*\s+(\d{1,2})\b|\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\b", text)
    if day:
        month_name, number = (day.group(1), day.group(2)) if day.group(1) else (day.group(4), day.group(3))
        month = _MONTHS.get(month_name.lower())
        if month:
            moment = now.replace(month=month, day=int(number), hour=hour, minute=minute, second=0, microsecond=0)
            if moment < now - timedelta(days=1):  # "Jan 2" seen in late December
                moment = moment.replace(year=moment.year + 1)
            return int(moment.timestamp())
    moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment < now:
        moment += timedelta(days=1)
    return int(moment.timestamp())


def parse_claude_usage(screen: str, now: datetime) -> list[dict[str, Any]]:
    """Claude Code `/usage`: 'Current session … 76% used / Resets 5:49pm (…)', 'Current week (all models) …'."""
    windows: list[dict[str, Any]] = []
    lines = screen.splitlines()
    for heading, kind in (("Current session", "five_hour"), ("Current week (all models)", "seven_day")):
        for index, line in enumerate(lines):
            if line.strip().startswith(heading):
                block = "\n".join(lines[index + 1:index + 4])
                used = re.search(r"(\d+(?:\.\d+)?)%\s*used", block)
                reset = re.search(r"Resets\s+(.+)", block)
                if used:
                    windows.append({"kind": kind, "used_percent": float(used.group(1)),
                                    "resets_at": parse_reset(reset.group(1), now) if reset else None})
                break
    return windows


def parse_codex_status(screen: str, now: datetime) -> list[dict[str, Any]]:
    """Codex `/status`: '5h limit: […] 100% left (resets 8:57 PM)', 'Weekly limit: […] 90% left (resets …)'."""
    windows: list[dict[str, Any]] = []
    for label, kind in (("5h limit", "five_hour"), ("Weekly limit", "seven_day")):
        match = re.search(rf"{label}:.*?(\d+(?:\.\d+)?)%\s*left(?:\s*\(resets\s+([^)]+)\))?", screen)
        if match:
            windows.append({"kind": kind, "used_percent": max(0.0, 100.0 - float(match.group(1))),
                            "resets_at": parse_reset(match.group(2), now) if match.group(2) else None})
    return windows


async def probe_limits(kind: str, config_dir: str | None) -> tuple[list[dict[str, Any]], str]:
    """Windows of a subscription account and the screen they were read from (for an error message)."""
    home = Path(os.path.expanduser(config_dir or "~"))
    env = dict(os.environ)
    if kind == "claude_code_subscription":
        argv = [shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")]
        env["CLAUDE_CONFIG_DIR"] = str(home)
        command, parse = "/usage", parse_claude_usage
    elif kind == "codex_subscription":
        # Without the shared background server: a profile with MCP OAuth coordination refuses it, and the
        # probe must not leave a daemon behind. No update prompt either: the probe would answer it.
        argv = [shutil.which("codex") or "codex", "--no-daemon", "-c", "check_for_update_on_startup=false"]
        env["CODEX_HOME"] = str(home)
        command, parse = "/status", parse_codex_status
    else:
        raise ValueError(f"unsupported account kind {kind}")
    workdir = Path(os.path.expanduser("~/.cache/aihub-usage-probe"))
    # A second try covers a one-off screen in front of the prompt (a CLI that just updated itself, a notice).
    for _ in range(2):
        screen = await asyncio.to_thread(read_slash_command, argv, env, command, workdir)
        windows = parse(screen, datetime.now(_local_zone()))
        if windows:
            break
    return windows, screen
