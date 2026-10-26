"""Authenticated principal envelope used at the knowledge HTTP boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    project_ids: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def sign_principal(principal: Principal, secret: str) -> str:
    payload = json.dumps(
        {"user_id": principal.user_id, "role": principal.role, "project_ids": sorted(principal.project_ids)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"v1.{encoded}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def parse_principal(header: str | None, secret: str) -> Principal:
    if not header or not secret:
        raise ValueError("missing principal or internal secret")
    try:
        version, encoded, supplied = header.split(".", 2)
        if version != "v1":
            raise ValueError("unsupported principal version")
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("invalid principal signature")
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if not isinstance(data, dict) or not isinstance(data["user_id"], str) or not isinstance(data["role"], str):
            raise TypeError("invalid principal payload")
        projects = data.get("project_ids", [])
        if not isinstance(projects, list) or not all(isinstance(p, str) for p in projects):
            raise TypeError("invalid project ids")
        return Principal(data["user_id"], data["role"], frozenset(projects))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid principal") from exc
