"""Markdown link extraction and graph assembly for the knowledge vault."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

WIKI_LINK_RE = re.compile(r"!??\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


@dataclass(frozen=True)
class ExtractedLink:
    target: str
    embedded: bool = False
    relative: bool = False


def extract_links(markdown: str) -> list[ExtractedLink]:
    """Extract Obsidian wikilinks/embeds and relative markdown links.

    External URLs, anchors, and non-markdown relative links are intentionally
    ignored: the graph represents notes in this vault.
    """
    links: list[ExtractedLink] = []
    for match in WIKI_LINK_RE.finditer(markdown):
        raw = match.group(1).strip()
        if raw:
            target = raw.split("|", 1)[0].strip()
            links.append(ExtractedLink(target.split("#", 1)[0].strip(), match.group(0).startswith("![")))
    for match in MARKDOWN_LINK_RE.finditer(markdown):
        raw = match.group(1).strip().split()[0].strip("<>")
        if not raw or raw.startswith(("#", "/", "//")) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw):
            continue
        path = raw.split("#", 1)[0]
        if path.lower().endswith(".md"):
            links.append(ExtractedLink(path, relative=True))
    return links


def resolve_link(link: ExtractedLink, source_path: str, documents: Iterable[object]) -> object | None:
    """Resolve a link by relative path/stem first, then by title, case-insensitively."""
    docs = list(documents)
    target = link.target.strip()
    if not target:
        return None
    source_dir = posixpath.dirname(source_path)
    candidate_path = posixpath.normpath(posixpath.join(source_dir, target)) if link.relative else None
    target_key = target.casefold()
    path_matches = []
    for doc in docs:
        path = str(doc.path).replace("\\", "/")
        stem = PurePosixPath(path).stem.casefold()
        if (candidate_path and path.casefold() == candidate_path.casefold()) or (
            not candidate_path and (stem == target_key or path.casefold() == f"{target_key}.md")
        ):
            path_matches.append(doc)
    if path_matches:
        return min(path_matches, key=lambda doc: str(doc.id))
    title_matches = [doc for doc in docs if str(doc.title).casefold() == target_key]
    return min(title_matches, key=lambda doc: str(doc.id)) if title_matches else None


def ghost_id(target: str) -> str:
    normalized = re.sub(r"\s+", " ", target.strip()).casefold()
    return f"ghost:{normalized}"
