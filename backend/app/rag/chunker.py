"""Code-aware semantic chunker for repository files and parse results.

Produces stable, deterministic chunks with exact line numbers matching the Code Viewer.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

WINDOW_SIZE = 60
WINDOW_OVERLAP = 10
WINDOW_STEP = WINDOW_SIZE - WINDOW_OVERLAP  # 50 lines


@dataclass
class CodeChunk:
    """A semantic chunk of code, documentation, or configuration."""

    chunk_id: str
    repo_id: str
    path: str
    language: str | None
    kind: str  # function | method | class | module | notebook_cell | doc_section | config | schema | window
    symbol_name: str | None
    start_line: int  # 1-based
    end_line: int  # 1-based
    text: str
    embed_text: str


def _split_long_chunk(
    repo_id: str,
    path: str,
    language: str | None,
    kind: str,
    symbol_name: str | None,
    start_line: int,
    end_line: int,
    text: str,
) -> list[CodeChunk]:
    """Split any chunk exceeding WINDOW_SIZE lines into overlapping windows."""
    lines = text.splitlines()
    if len(lines) <= WINDOW_SIZE:
        prefix = f"{path} > {symbol_name}" if symbol_name else path
        embed_text = f"{prefix}\n{text}"
        chunk_id = f"{path}:{symbol_name or kind}:{start_line}"
        return [
            CodeChunk(
                chunk_id=chunk_id,
                repo_id=repo_id,
                path=path,
                language=language,
                kind=kind,
                symbol_name=symbol_name,
                start_line=start_line,
                end_line=end_line,
                text=text,
                embed_text=embed_text,
            )
        ]

    chunks: list[CodeChunk] = []
    total_lines = len(lines)
    for i in range(0, total_lines, WINDOW_STEP):
        w_lines = lines[i : i + WINDOW_SIZE]
        if not w_lines:
            break
        w_start = start_line + i
        w_end = min(end_line, start_line + i + len(w_lines) - 1)
        w_text = "\n".join(w_lines)
        if not w_text.strip():
            continue

        prefix = f"{path} > {symbol_name} (lines {w_start}-{w_end})" if symbol_name else f"{path} (lines {w_start}-{w_end})"
        embed_text = f"{prefix}\n{w_text}"
        chunk_id = f"{path}:{symbol_name or kind}:{w_start}-{w_end}"

        chunks.append(
            CodeChunk(
                chunk_id=chunk_id,
                repo_id=repo_id,
                path=path,
                language=language,
                kind="window",
                symbol_name=symbol_name,
                start_line=w_start,
                end_line=w_end,
                text=w_text,
                embed_text=embed_text,
            )
        )
        if i + WINDOW_SIZE >= total_lines:
            break

    return chunks


def _chunk_code_file(
    repo_id: str,
    path: str,
    content: str,
    language: str | None,
    symbols: list[dict[str, Any]],
) -> list[CodeChunk]:
    """Chunk code file using functions, methods, class headers, and module chunks."""
    all_lines = content.splitlines()
    total_file_lines = len(all_lines)
    if total_file_lines == 0 or not content.strip():
        return []

    chunks: list[CodeChunk] = []
    covered_lines: set[int] = set()

    # Sort symbols by start_line
    sorted_symbols = sorted(symbols, key=lambda s: s.get("start_line", 1))

    # Separate classes and functions/methods
    classes = [s for s in sorted_symbols if s.get("kind") == "class"]
    functions = [s for s in sorted_symbols if s.get("kind") in ("function", "method")]

    # 1. Class headers: from class definition up to the first method
    for cls in classes:
        cls_name = cls.get("name", "")
        c_start = cls.get("start_line", 1)
        c_end = cls.get("end_line", total_file_lines)

        # Find first method inside this class
        child_methods = [
            f for f in functions
            if f.get("start_line", 0) > c_start and f.get("end_line", 0) <= c_end
        ]
        if child_methods:
            first_m_start = min(f.get("start_line", c_end) for f in child_methods)
            header_end = max(c_start, first_m_start - 1)
        else:
            header_end = c_end

        header_lines = all_lines[c_start - 1 : header_end]
        header_text = "\n".join(header_lines)
        if header_text.strip():
            for line_no in range(c_start, header_end + 1):
                covered_lines.add(line_no)
            chunks.extend(
                _split_long_chunk(
                    repo_id=repo_id,
                    path=path,
                    language=language,
                    kind="class",
                    symbol_name=cls_name,
                    start_line=c_start,
                    end_line=header_end,
                    text=header_text,
                )
            )

    # 2. Functions and methods
    for fn in functions:
        fn_name = fn.get("name", "")
        f_kind = fn.get("kind", "function")
        f_start = fn.get("start_line", 1)
        f_end = min(fn.get("end_line", total_file_lines), total_file_lines)

        fn_lines = all_lines[f_start - 1 : f_end]
        fn_text = "\n".join(fn_lines)
        if fn_text.strip():
            for line_no in range(f_start, f_end + 1):
                covered_lines.add(line_no)
            chunks.extend(
                _split_long_chunk(
                    repo_id=repo_id,
                    path=path,
                    language=language,
                    kind=f_kind,
                    symbol_name=fn_name,
                    start_line=f_start,
                    end_line=f_end,
                    text=fn_text,
                )
            )

    # 3. Module chunk: uncovered top-level statements/imports before the first symbol
    if sorted_symbols:
        first_sym_start = min(s.get("start_line", 1) for s in sorted_symbols)
        if first_sym_start > 1:
            module_lines = all_lines[: first_sym_start - 1]
            module_text = "\n".join(module_lines)
            if module_text.strip():
                chunks.extend(
                    _split_long_chunk(
                        repo_id=repo_id,
                        path=path,
                        language=language,
                        kind="module",
                        symbol_name=None,
                        start_line=1,
                        end_line=first_sym_start - 1,
                        text=module_text,
                    )
                )

    # If no symbols or entire file had no chunks, chunk as window(s)
    if not chunks:
        chunks.extend(
            _split_long_chunk(
                repo_id=repo_id,
                path=path,
                language=language,
                kind="module",
                symbol_name=None,
                start_line=1,
                end_line=total_file_lines,
                text=content,
            )
        )

    return chunks


def _chunk_notebook(repo_id: str, path: str, content: str) -> list[CodeChunk]:
    """Chunk Jupyter notebook by individual cell with cell type and index."""
    try:
        nb_data = json.loads(content)
        cells = nb_data.get("cells", [])
    except Exception:
        return _split_long_chunk(repo_id, path, "jupyter", "notebook_cell", None, 1, 1, content)

    chunks: list[CodeChunk] = []
    line_cursor = 1

    for idx, cell in enumerate(cells):
        cell_type = cell.get("cell_type", "code")
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        if not source.strip():
            continue

        c_lines = source.splitlines()
        c_count = len(c_lines) or 1
        c_start = line_cursor
        c_end = line_cursor + c_count - 1
        line_cursor += c_count

        symbol_name = f"cell_{idx}_{cell_type}"
        chunks.extend(
            _split_long_chunk(
                repo_id=repo_id,
                path=path,
                language="jupyter",
                kind="notebook_cell",
                symbol_name=symbol_name,
                start_line=c_start,
                end_line=c_end,
                text=source,
            )
        )

    return chunks


def _chunk_markdown(repo_id: str, path: str, content: str) -> list[CodeChunk]:
    """Chunk documentation by primary heading sections (H1/H2)."""
    lines = content.splitlines()
    if not lines:
        return []

    heading_indices: list[int] = []
    heading_titles: list[str] = []

    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,2})\s+(.+)", line)
        if m:
            heading_indices.append(idx)
            heading_titles.append(m.group(2).strip())

    if not heading_indices:
        return _split_long_chunk(repo_id, path, "markdown", "doc_section", None, 1, len(lines), content)

    chunks: list[CodeChunk] = []
    # Text before first heading
    if heading_indices[0] > 0:
        pre_text = "\n".join(lines[: heading_indices[0]])
        if pre_text.strip():
            chunks.extend(
                _split_long_chunk(
                    repo_id=repo_id,
                    path=path,
                    language="markdown",
                    kind="doc_section",
                    symbol_name="Intro",
                    start_line=1,
                    end_line=heading_indices[0],
                    text=pre_text,
                )
            )

    for i, start_idx in enumerate(heading_indices):
        end_idx = heading_indices[i + 1] if i + 1 < len(heading_indices) else len(lines)
        section_lines = lines[start_idx:end_idx]
        section_text = "\n".join(section_lines)
        if not section_text.strip():
            continue
        title = heading_titles[i]
        chunks.extend(
            _split_long_chunk(
                repo_id=repo_id,
                path=path,
                language="markdown",
                kind="doc_section",
                symbol_name=title,
                start_line=start_idx + 1,
                end_line=end_idx,
                text=section_text,
            )
        )

    return chunks


def build_file_chunks(
    repo_id: str,
    path: str,
    content: str,
    language: str | None,
    parsed_file_data: Optional[dict[str, Any]] = None,
) -> list[CodeChunk]:
    """Build semantic chunks for a single repo file based on its kind and parse facts."""
    if not content or not content.strip():
        return []

    # Skip lockfiles, minified files, maps, and bundles
    basename = path.split("/")[-1].lower()
    if basename in (
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "cargo.lock",
        "composer.lock",
        "mix.lock",
        "gemfile.lock",
    ) or path.endswith((".min.js", ".min.css", ".map", ".bundle.js", ".lock")):
        return []

    kind = parsed_file_data.get("kind", "other") if parsed_file_data else "other"
    symbols = parsed_file_data.get("symbols", []) if parsed_file_data else []
    summary_hint = parsed_file_data.get("summary_hint", "") if parsed_file_data else ""

    # Notebooks
    if kind == "notebook" or path.endswith(".ipynb"):
        return _chunk_notebook(repo_id, path, content)

    # Documentation
    if kind == "doc" or path.endswith((".md", ".rst", ".txt")):
        return _chunk_markdown(repo_id, path, content)

    # Config files: one chunk of structured facts per file
    if kind == "config":
        facts_text = summary_hint if summary_hint else content
        return [
            CodeChunk(
                chunk_id=f"{path}:config:1",
                repo_id=repo_id,
                path=path,
                language=language or "config",
                kind="config",
                symbol_name=None,
                start_line=1,
                end_line=min(60, len(content.splitlines()) or 1),
                text=facts_text,
                embed_text=f"{path} > config\n{facts_text}",
            )
        ]

    # SQL files: one chunk per table or section
    if kind == "sql" or path.endswith(".sql"):
        if symbols:
            chunks: list[CodeChunk] = []
            for sym in symbols:
                s_name = sym.get("name", "table")
                s_start = sym.get("start_line", 1)
                s_end = sym.get("end_line", len(content.splitlines()))
                t_lines = content.splitlines()[s_start - 1 : s_end]
                chunks.extend(
                    _split_long_chunk(
                        repo_id=repo_id,
                        path=path,
                        language="sql",
                        kind="schema",
                        symbol_name=s_name,
                        start_line=s_start,
                        end_line=s_end,
                        text="\n".join(t_lines),
                    )
                )
            if chunks:
                return chunks
        return _split_long_chunk(repo_id, path, "sql", "schema", None, 1, len(content.splitlines()), content)

    # Data files (CSV/JSON): one schema chunk per file, never whole file
    if kind == "data" or path.endswith((".csv", ".tsv")):
        schema_text = summary_hint if summary_hint else f"Data schema for {path}"
        return [
            CodeChunk(
                chunk_id=f"{path}:schema:1",
                repo_id=repo_id,
                path=path,
                language=language or "data",
                kind="schema",
                symbol_name=None,
                start_line=1,
                end_line=1,
                text=schema_text,
                embed_text=f"{path} > schema\n{schema_text}",
            )
        ]

    # Code files (Python, JS, TS, etc.)
    return _chunk_code_file(repo_id, path, content, language, symbols)


def chunk_file(
    path: str,
    content: str,
    language: str | None = None,
    parse_info: Optional[dict[str, Any]] = None,
    repo_id: str = "",
) -> list[CodeChunk]:
    """Convenience alias for building semantic file chunks."""
    return build_file_chunks(repo_id, path, content, language, parse_info)
