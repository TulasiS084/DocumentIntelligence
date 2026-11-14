"""Parse markdown and documentation files."""

from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import unquote, urlparse

from app.ingest.parsers.models import ParsedFile

logger = logging.getLogger(__name__)

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)

# Markdown links: [text](url) — skip external URLs and anchors-only
_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Reference-style images / links that could point to repo files
_IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _is_relative_file_link(url: str) -> bool:
    """Return True if *url* is a relative path (not http, mailto, anchor-only, etc.)."""
    if not url:
        return False
    if url.startswith("#"):
        return False
    parsed = urlparse(url)
    # Has scheme → external link
    if parsed.scheme:
        return False
    return True


def _clean_link(url: str) -> str:
    """Normalise a relative link to a POSIX repo-relative path."""
    # Strip anchor fragments
    url = url.split("#")[0]
    # Strip query strings
    url = url.split("?")[0]
    # Decode percent-encoded characters
    url = unquote(url)
    # Normalise slashes
    url = url.replace("\\", "/")
    # Remove leading ./
    if url.startswith("./"):
        url = url[2:]
    return url


def parse_markdown(
    path: str,
    language: str,
    content: str,
    all_paths: set[str],
) -> ParsedFile:
    """Parse a markdown document and return a ParsedFile.

    Splits by heading, extracts relative file links, and produces
    a summary hint from the first heading or first paragraph.
    """
    headings: list[str] = []
    references: list[str] = []
    seen_refs: set[str] = set()

    # --- Headings ---
    for match in _HEADING_PATTERN.finditer(content):
        headings.append(match.group(2).strip())

    # --- Links ---
    for pattern in (_LINK_PATTERN, _IMG_PATTERN):
        for match in pattern.finditer(content):
            url = match.group(2).strip()
            if _is_relative_file_link(url):
                cleaned = _clean_link(url)
                if cleaned and cleaned not in seen_refs:
                    # Resolve relative to the markdown file's directory
                    parent_dir = str(PurePosixPath(path).parent)
                    if parent_dir == ".":
                        resolved = cleaned
                    else:
                        resolved = f"{parent_dir}/{cleaned}"
                    # Normalise parent references
                    try:
                        parts = PurePosixPath(resolved).parts
                        normalised: list[str] = []
                        for part in parts:
                            if part == "..":
                                if normalised:
                                    normalised.pop()
                            elif part != ".":
                                normalised.append(part)
                        resolved = "/".join(normalised) if normalised else cleaned
                    except Exception:
                        resolved = cleaned

                    if resolved in all_paths:
                        references.append(resolved)
                        seen_refs.add(cleaned)
                    elif cleaned in all_paths:
                        references.append(cleaned)
                        seen_refs.add(cleaned)

    # --- Summary hint ---
    summary_hint = ""
    if headings:
        summary_hint = headings[0]
    else:
        # First non-empty paragraph
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("<!--"):
                summary_hint = stripped[:200]
                break
    if not summary_hint:
        summary_hint = "Markdown document"

    return ParsedFile(
        path=path,
        language=language or "markdown",
        kind="doc",
        references=references,
        summary_hint=summary_hint,
    )
