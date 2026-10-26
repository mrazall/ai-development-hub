"""Small, documented-API client for the optional Codeman session layer.

Codeman owns the terminal/session lifecycle.  This module deliberately keeps
the client independent from ``worker.py`` so the worker can decide when to
translate these events into the Hub event contract.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from .adapters import AgentEvent

_DEFAULT_URL = "http://127.0.0.1:3000"
_PASSWORD_FILE = Path("~/.aihub/codeman.env")


def _password() -> str | None:
    """Read only CODEMAN_PASSWORD from the local env file; never expose it."""
    path = _PASSWORD_FILE.expanduser()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return os.environ.get("CODEMAN_PASSWORD") or None
    for line in lines:
        key, separator, value = line.partition("=")
        if key.strip() == "CODEMAN_PASSWORD" and separator:
            return value.strip().strip("\"'") or None
    return os.environ.get("CODEMAN_PASSWORD") or None


def _base_url() -> str:
    return (os.environ.get("AIHUB_CODEMAN_URL") or os.environ.get("CODEMAN_API_URL") or _DEFAULT_URL).rstrip("/")


class CodemanClient:
    """Synchronous Codeman REST/SSE client, injectable for deterministic tests."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        password: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or _base_url()).rstrip("/")
        self.password = _password() if password is None else password
        self.transport = transport

    def _client(self) -> httpx.Client:
        username = os.environ.get("CODEMAN_USERNAME", "codeman")
        auth = httpx.BasicAuth(username, self.password) if self.password else None
        return httpx.Client(base_url=self.base_url, auth=auth, transport=self.transport, timeout=30.0)

    @staticmethod
    def _data(response: httpx.Response) -> Any:
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict) and body.get("success") is False:
            raise RuntimeError(str(body.get("error") or body.get("message") or "Codeman request failed"))
        if isinstance(body, dict) and body.get("success") is True:
            return body.get("data")
        return body

    def create_session(self, cli: str, workdir: str, title: str) -> str:
        """Create and start a Codeman session; return its opaque session id."""
        with self._client() as client:
            response = client.post(
                "/api/v1/sessions",
                json={"workingDir": str(workdir), "mode": cli, "name": title},
            )
            data = self._data(response)
            session = data.get("session", data) if isinstance(data, dict) else {}
            ref = session.get("id") or session.get("sessionId") if isinstance(session, dict) else None
            if not ref:
                raise RuntimeError("Codeman create response did not contain a session id")
            start = client.post(f"/api/v1/sessions/{ref}/interactive", json={})
            self._data(start)
            return str(ref)

    def stop_session(self, ref: str) -> None:
        """Stop a session using Codeman's documented interrupt input."""
        with self._client() as client:
            response = client.post(f"/api/v1/sessions/{ref}/input", json={"input": "\u001b"})
            self._data(response)

    def send_input(self, ref: str, text: str) -> None:
        """Send interactive input using the documented Codeman endpoint."""
        with self._client() as client:
            response = client.post(f"/api/v1/sessions/{ref}/input", json={"input": text})
            self._data(response)

    def iter_events(self, ref: str) -> Iterator[AgentEvent]:
        """Yield SSE frames from Codeman's filtered event channel."""
        with self._client() as client, client.stream("GET", "/api/events", params={"sessions": ref}) as response:
                response.raise_for_status()
                event_name = "message"
                data_lines: list[str] = []
                for line in response.iter_lines():
                    if line == "":
                        if data_lines:
                            yield self._event(event_name, "\n".join(data_lines))
                        event_name, data_lines = "message", []
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                if data_lines:
                    yield self._event(event_name, "\n".join(data_lines))

    @staticmethod
    def _event(event_name: str, raw_data: str) -> AgentEvent:
        try:
            payload: dict[str, Any] = json.loads(raw_data)
        except json.JSONDecodeError:
            payload = {"text": raw_data}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        source = "cli_parser" if event_name.startswith(("terminal:", "output:", "session:output")) else "native"
        return AgentEvent(event_name, payload, source)


def create_session(cli: str, workdir: str, title: str) -> str:
    return CodemanClient().create_session(cli, workdir, title)


def stop_session(ref: str) -> None:
    CodemanClient().stop_session(ref)


def iter_events(ref: str) -> Iterator[AgentEvent]:
    return CodemanClient().iter_events(ref)


__all__ = ["CodemanClient", "create_session", "iter_events", "stop_session"]
