"""The signed principal envelope sent to the knowledge service."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

from .config import Settings


def sign_principal(user, project_ids=None) -> str:
    """Sign a user principal in the format consumed by knowledge/acl.py."""
    if project_ids is None:
        project_ids = getattr(user, "project_ids", ())
    payload = json.dumps(
        {
            "user_id": user.id,
            "role": user.role,
            "project_ids": sorted(set(project_ids)),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    secret = Settings().internal_secret
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    signed = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"v1.{encoded}.{signed}"
