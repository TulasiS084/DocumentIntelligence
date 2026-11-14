"""Parser registry: dispatches files to appropriate specialized parsers."""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import Optional

from app.ingest.parsers.code import parse_code_file
from app.ingest.parsers.config_files import parse_config
from app.ingest.parsers.data_files import parse_data_file
from app.ingest.parsers.markdown_doc import parse_markdown
from app.ingest.parsers.models import ParsedFile
from app.ingest.parsers.notebook import parse_notebook
from app.ingest.parsers.sql import parse_sql

logger = logging.getLogger(__name__)

CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
DOC_EXTENSIONS = {".md", ".markdown", ".mdx", ".rst", ".txt"}
CONFIG_FILENAMES = {
    "package.json",
    "package-lock.json",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "makefile",
    "cmakelists.txt",
    ".env",
    ".env.example",
    "tsconfig.json",
}
CONFIG_EXTENSIONS = {".yml", ".yaml", ".toml", ".ini", ".cfg"}
DATA_EXTENSIONS = {".csv", ".tsv"}


def parse_file(
    path: str,
    content: str = "",
    language: Optional[str] = None,
    all_paths: Optional[set[str]] = None,
    **kwargs: object,
) -> ParsedFile:
    """Dispatch a file to the appropriate parser based on extension and filename.

    Accepts arguments positionally or as keywords to accommodate callers passing
    either (path, content, language) or (path, language, content, all_paths).
    """
    # Accommodate callers that pass (path, language, content, all_paths)
    if isinstance(content, str) and isinstance(language, str) and content in {
        "python", "javascript", "typescript", "markdown", "json", "yaml", "sql", "jupyter", "html", "css"
    } and len(content) < len(language):
        # User passed (path, language, content)
        actual_language = content
        actual_content = language
    else:
        actual_language = language or ""
        actual_content = content

    paths_set: set[str] = all_paths if all_paths is not None else set()
    if "all_paths" in kwargs and isinstance(kwargs["all_paths"], set):
        paths_set = kwargs["all_paths"]  # type: ignore[assignment]

    posix = PurePosixPath(path)
    filename = posix.name.lower()
    ext = posix.suffix.lower()

    try:
        if ext in CODE_EXTENSIONS or actual_language in {"python", "javascript", "typescript"}:
            return parse_code_file(path, actual_language or "code", actual_content, paths_set)

        if ext == ".ipynb" or actual_language == "jupyter":
            return parse_notebook(path, actual_language or "jupyter", actual_content, paths_set)

        if ext in DOC_EXTENSIONS or actual_language in {"markdown", "text"}:
            return parse_markdown(path, actual_language or "markdown", actual_content, paths_set)

        if (
            filename in CONFIG_FILENAMES
            or filename.startswith("dockerfile")
            or filename.startswith(".env")
            or ext in CONFIG_EXTENSIONS
            or (ext == ".json" and ("config" in filename or filename in CONFIG_FILENAMES))
        ):
            return parse_config(path, actual_language or "config", actual_content, paths_set)

        if ext == ".sql" or actual_language == "sql":
            return parse_sql(path, actual_language or "sql", actual_content, paths_set)

        if ext in DATA_EXTENSIONS or (ext == ".json" and filename not in CONFIG_FILENAMES):
            return parse_data_file(path, actual_language or "data", actual_content, paths_set)

        # Fallback for other files
        return ParsedFile(
            path=path,
            language=actual_language or "other",
            kind="other",
            summary_hint=f"File: {path}",
        )
    except Exception as exc:
        logger.warning("Error parsing file %s: %s", path, exc, exc_info=True)
        return ParsedFile(
            path=path,
            language=actual_language or "other",
            kind="other",
            summary_hint=f"File: {path} (parse error)",
            parse_error=str(exc) or "parse error",
        )
