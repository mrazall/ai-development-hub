import math
import re
from typing import Any

TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
PATTERNS = [
    # word boundary: "desk-top"/"task-runner" are not keys
    re.compile(r"\bsk-[A-Za-z0-9_-]{4,}"),
    re.compile(r"ghp_[A-Za-z0-9]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"AIza[A-Za-z0-9_-]+"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [^-]+ PRIVATE KEY-----"),
    # Whole header value up to end of line: scheme and credential alike.
    re.compile(r"(?i)((?:Proxy-)?Authorization\s*:\s*)[^\r\n]+"),
    re.compile(r"(?i)((?:Set-)?Cookie\s*:\s*)[^\r\n]+"),
    re.compile(r"(?i)(?:password|token)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@[^\s]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
]


def entropy(value: str) -> float:
    length = len(value)
    counts = {char: value.count(char) for char in set(value)}
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


_WORD = r"(?:[A-Z]?[a-z0-9]+|[A-Z0-9]+)"
_WORDY = re.compile(rf"{_WORD}(?:[._-]+{_WORD})*[._-]*")


def _looks_like_path(token: str) -> bool:
    """Filesystem paths (/home/dev/projects/hello-hub/README.md) are long and high-entropy but not secrets.
    A path segment reads like a word or file name; random base64 segments mix case and digits."""
    if "/" not in token:
        return False
    segments = [segment for segment in token.split("/") if segment]
    return len(segments) >= 2 and all(_WORDY.fullmatch(segment) for segment in segments)


def redact_string(value: str) -> tuple[str, bool]:
    changed = False
    result = value
    for pattern in PATTERNS:
        replacement = (
            r"\1[REDACTED]" if pattern.groups else "[REDACTED]"
        )
        result, count = pattern.subn(replacement, result)
        changed |= bool(count)

    def replace_token(match: re.Match[str]) -> str:
        nonlocal changed
        token = match.group(0)
        if _looks_like_path(token):
            return token
        if entropy(token) >= 4.0:
            changed = True
            return "[REDACTED]"
        return token

    return TOKEN.sub(replace_token, result), changed


def redact(value: Any, in_output: bool = False) -> tuple[Any, bool]:
    if isinstance(value, dict):
        result = {}
        changed = False
        for key, item in value.items():
            redacted, item_changed = redact(item, in_output or key.lower() == "output")
            result[key] = redacted
            changed |= item_changed
        return result, changed
    if isinstance(value, list):
        result = []
        changed = False
        for item in value:
            redacted, item_changed = redact(item, in_output)
            result.append(redacted)
            changed |= item_changed
        return result, changed
    if isinstance(value, str):
        return redact_string(value)
    return value, False
