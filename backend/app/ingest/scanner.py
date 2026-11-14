"""Walk a cloned repository and build a nested file-tree with stats."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

IGNORED_DIR_NAMES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
}

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".tgz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".class",
    ".pyc",
    ".pyo",
    ".pyd",
    ".o",
    ".obj",
    ".a",
    ".lib",
    ".wasm",
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".sqlite",
    ".sqlite3",
    ".npy",
    ".pkl",
    ".pickle",
    ".parquet",
    ".whl",
}

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".md": "markdown",
    ".mdx": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".sql": "sql",
    ".ipynb": "jupyter",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".txt": "text",
}

SPECIAL_FILENAMES = {
    "dockerfile": "dockerfile",
}


@dataclass
class ScanCounters:
    """Mutable counters used while walking a tree."""

    files_analyzed: int = 0
    total_files: int = 0
    total_directories: int = 0
    skipped_count: int = 0
    files_by_language: dict[str, int] = field(default_factory=dict)


def _posix_rel(root: Path, path: Path) -> str:
    """Relative POSIX path, or ``.`` for the root itself."""
    rel = path.resolve().relative_to(root.resolve())
    text = rel.as_posix()
    return "." if text == "." else text


def _is_under(path: Path, parent: Path) -> bool:
    """Return True if path resolves inside parent."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def detect_language(name: str, ext: Optional[str]) -> Optional[str]:
    """Map a filename/extension to a language label."""
    if name.lower() in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[name.lower()]
    if ext:
        return LANGUAGE_BY_EXT.get(ext.lower())
    return None


def is_binary_file(path: Path, ext: Optional[str]) -> bool:
    """Treat a file as binary by extension or a NUL in the first 1024 bytes."""
    if ext and ext.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with path.open("rb") as handle:
            chunk = handle.read(1024)
        return b"\x00" in chunk
    except OSError:
        logger.debug("Could not read %s for binary detection", path, exc_info=True)
        return True


def count_lines(path: Path) -> int:
    """Count newline-separated lines in a text file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.debug("Could not read %s for line count", path, exc_info=True)
        return 0
    if not text:
        return 0
    return len(text.splitlines())


def _empty_node(
    name: str,
    rel_path: str,
    node_type: str,
    *,
    ext: Optional[str] = None,
    language: Optional[str] = None,
    size: int = 0,
    loc: Optional[int] = None,
    skipped: bool = False,
    skip_reason: Optional[str] = None,
    children: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Build a tree node with the Step 1 schema."""
    return {
        "name": name,
        "path": rel_path,
        "type": node_type,
        "ext": ext,
        "language": language,
        "size": size,
        "loc": loc,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "summary": None,
        "children": children,
    }


def _sort_children(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Directories first, then files, alphabetically by name."""
    return sorted(
        nodes,
        key=lambda node: (0 if node["type"] == "dir" else 1, node["name"].lower()),
    )


def _scan_file(
    root: Path,
    path: Path,
    counters: ScanCounters,
    max_files: int,
    max_file_size: int,
) -> dict[str, Any]:
    """Create a file node, applying skip rules."""
    counters.total_files += 1
    rel = _posix_rel(root, path)
    ext = path.suffix.lower() or None
    language = detect_language(path.name, ext)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    if counters.files_analyzed >= max_files:
        counters.skipped_count += 1
        return _empty_node(
            path.name,
            rel,
            "file",
            ext=ext,
            language=language,
            size=size,
            skipped=True,
            skip_reason="limit_reached",
        )

    counters.files_analyzed += 1

    if size > max_file_size:
        counters.skipped_count += 1
        return _empty_node(
            path.name,
            rel,
            "file",
            ext=ext,
            language=language,
            size=size,
            skipped=True,
            skip_reason="too_large",
        )

    if is_binary_file(path, ext):
        counters.skipped_count += 1
        return _empty_node(
            path.name,
            rel,
            "file",
            ext=ext,
            language=language,
            size=size,
            skipped=True,
            skip_reason="binary",
        )

    loc = count_lines(path)
    lang_key = language or "other"
    counters.files_by_language[lang_key] = counters.files_by_language.get(lang_key, 0) + 1
    return _empty_node(
        path.name,
        rel,
        "file",
        ext=ext,
        language=language,
        size=size,
        loc=loc,
        skipped=False,
        skip_reason=None,
    )


def _iter_entries(directory: Path, root: Path) -> list[Path]:
    """List directory entries that stay inside the clone root."""
    entries: list[Path] = []
    try:
        children = list(directory.iterdir())
    except OSError:
        logger.debug("Could not list %s", directory, exc_info=True)
        return entries
    for child in children:
        if child.is_symlink():
            resolved = child.resolve()
            if not _is_under(resolved, root):
                logger.warning("Skipping symlink outside clone: %s -> %s", child, resolved)
                continue
            # Do not follow directory symlinks; skip them as ignored.
            if resolved.is_dir():
                continue
        if not _is_under(child, root):
            continue
        entries.append(child)
    return entries


def _scan_dir(
    root: Path,
    directory: Path,
    counters: ScanCounters,
    max_files: int,
    max_file_size: int,
    is_root: bool = False,
) -> dict[str, Any]:
    """Recursively scan a directory."""
    if not is_root:
        counters.total_directories += 1
    rel = _posix_rel(root, directory)
    children: list[dict[str, Any]] = []

    for child in _iter_entries(directory, root):
        if child.is_dir():
            if child.name in IGNORED_DIR_NAMES:
                counters.total_directories += 1
                counters.skipped_count += 1
                children.append(
                    _empty_node(
                        child.name,
                        _posix_rel(root, child),
                        "dir",
                        skipped=True,
                        skip_reason="ignored",
                        children=[],
                    )
                )
                continue
            children.append(
                _scan_dir(root, child, counters, max_files, max_file_size, is_root=False)
            )
        elif child.is_file():
            children.append(
                _scan_file(root, child, counters, max_files, max_file_size)
            )

    return _empty_node(
        directory.name,
        rel,
        "dir",
        skipped=False,
        skip_reason=None,
        children=_sort_children(children),
    )


def scan_repository(root: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan ``root`` and return ``(tree, stats)``.

    Never follows symlinks outside the clone. Limits and skip rules come
    from application settings.
    """
    settings = get_settings()
    base = Path(root).resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"Clone directory does not exist: {base}")

    counters = ScanCounters()
    logger.info("Scanning %s", base)
    tree = _scan_dir(
        base,
        base,
        counters,
        settings.max_files_analyzed,
        settings.max_file_size_bytes,
        is_root=True,
    )
    stats = {
        "total_files": counters.total_files,
        "total_directories": counters.total_directories,
        "files_by_language": dict(sorted(counters.files_by_language.items())),
        "skipped_count": counters.skipped_count,
    }
    logger.info(
        "Scan complete: %s files, %s dirs, %s skipped",
        stats["total_files"],
        stats["total_directories"],
        stats["skipped_count"],
    )
    return tree, stats
