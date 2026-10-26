from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .vault import KnowledgeDocument


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    heading: str | None
    heading_path: str
    text: str
    content_hash: str
    line_start: int
    line_end: int


def _chunk_id(doc_id: str, heading_path: str, number: int) -> str:
    return hashlib.sha256(f"{doc_id}\0{heading_path}\0{number}".encode()).hexdigest()[:32]


def chunk_document(document: KnowledgeDocument, max_chars: int = 1200, overlap: int = 150) -> list[Chunk]:
    lines = document.content.splitlines()
    sections: list[tuple[str, list[str], int]] = []
    headings: list[str] = []
    current: list[str] = []
    start = 1
    for idx, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and current:
            sections.append((" / ".join(headings), current, start))
            current, start = [], idx
        if match:
            level, title = len(match.group(1)), match.group(2)
            headings = headings[: level - 1] + [title]
        current.append(line)
    if current:
        sections.append((" / ".join(headings), current, start))
    result: list[Chunk] = []
    for heading_path, section, section_start in sections:
        raw = "\n".join(section).strip()
        if not raw:
            continue
        cursor = 0
        number = 0
        while cursor < len(raw):
            end = min(len(raw), cursor + max_chars)
            text = raw[cursor:end].strip()
            line_start = section_start + raw[:cursor].count("\n")
            line_end = line_start + max(0, text.count("\n"))
            cid = _chunk_id(document.id, heading_path, number)
            result.append(
                Chunk(
                    cid,
                    document.id,
                    heading_path.split(" / ")[-1] if heading_path else None,
                    heading_path,
                    text,
                    hashlib.sha256(text.encode()).hexdigest(),
                    line_start,
                    line_end,
                )
            )
            if end == len(raw):
                break
            cursor = max(cursor + 1, end - overlap)
            number += 1
    return result
