"""Parse Jupyter notebook (.ipynb) files using nbformat."""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.ingest.parsers.models import CallInfo, ImportInfo, ParsedFile, SymbolDef

logger = logging.getLogger(__name__)

# Regex patterns for extracting information from code cells
_IMPORT_PATTERN = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+)?import\s+(.+)", re.MULTILINE
)
_FUNC_PATTERN = re.compile(r"^\s*def\s+(\w+)\s*\(", re.MULTILINE)
_CLASS_PATTERN = re.compile(r"^\s*class\s+(\w+)\s*[:\(]", re.MULTILINE)
_FILE_REF_PATTERN = re.compile(
    r"""(?:open|read_csv|read_json|read_excel|read_parquet|read_table"""
    r"""|to_csv|to_json|load|save|read_text|read_bytes"""
    r"""|readFile|writeFile)\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)


def parse_notebook(
    path: str,
    language: str,
    content: str,
    all_paths: set[str],
) -> ParsedFile:
    """Parse a Jupyter notebook file and return a ParsedFile.

    Extracts imports, function definitions, markdown headings,
    and data-file references from code cells. Builds a pipeline
    outline from headings and function names.
    """
    import nbformat

    try:
        nb = nbformat.reads(content, as_version=4)
    except Exception as exc:
        logger.warning("Failed to parse notebook %s: %s", path, exc)
        return ParsedFile(
            path=path,
            language=language or "jupyter",
            kind="notebook",
            summary_hint="Jupyter notebook (parse error)",
            parse_error=str(exc),
        )

    symbols: list[SymbolDef] = []
    imports: list[ImportInfo] = []
    calls: list[CallInfo] = []
    references: list[str] = []
    seen_refs: set[str] = set()
    pipeline_parts: list[str] = []

    cumulative_line = 0  # track approximate line numbers across cells

    for cell_idx, cell in enumerate(nb.cells):
        cell_source: str = cell.get("source", "")
        cell_type: str = cell.get("cell_type", "")
        cell_lines = cell_source.count("\n") + 1

        if cell_type == "markdown":
            for match in _HEADING_PATTERN.finditer(cell_source):
                pipeline_parts.append(match.group(2).strip())

        elif cell_type == "code":
            # --- Imports ---
            for match in _IMPORT_PATTERN.finditer(cell_source):
                from_module = match.group(1)
                import_part = match.group(2).strip()
                if from_module:
                    names = [n.strip().split(" as ")[0].strip() for n in import_part.split(",")]
                    imports.append(ImportInfo(
                        module=from_module,
                        names=names,
                        is_relative=from_module.startswith("."),
                    ))
                else:
                    for mod_str in import_part.split(","):
                        mod_str = mod_str.strip().split(" as ")[0].strip()
                        imports.append(ImportInfo(
                            module=mod_str,
                            names=[],
                            is_relative=False,
                        ))

            # --- Functions ---
            for match in _FUNC_PATTERN.finditer(cell_source):
                name = match.group(1)
                line_in_cell = cell_source[:match.start()].count("\n")
                symbols.append(SymbolDef(
                    name=name,
                    kind="function",
                    start_line=cumulative_line + line_in_cell + 1,
                    end_line=cumulative_line + line_in_cell + 1,
                ))
                pipeline_parts.append(name)

            # --- Classes ---
            for match in _CLASS_PATTERN.finditer(cell_source):
                name = match.group(1)
                line_in_cell = cell_source[:match.start()].count("\n")
                symbols.append(SymbolDef(
                    name=name,
                    kind="class",
                    start_line=cumulative_line + line_in_cell + 1,
                    end_line=cumulative_line + line_in_cell + 1,
                ))

            # --- File references ---
            for match in _FILE_REF_PATTERN.finditer(cell_source):
                candidate = match.group(1).replace("\\", "/")
                if candidate not in seen_refs:
                    if candidate in all_paths:
                        references.append(candidate)
                        seen_refs.add(candidate)

        cumulative_line += cell_lines

    # Build summary
    n_code = sum(1 for c in nb.cells if c.get("cell_type") == "code")
    n_md = sum(1 for c in nb.cells if c.get("cell_type") == "markdown")
    outline = " → ".join(pipeline_parts[:8]) if pipeline_parts else ""
    summary_parts = [f"Notebook with {n_code} code cells, {n_md} markdown cells"]
    if outline:
        summary_parts.append(f"pipeline: {outline}")
    summary_hint = "; ".join(summary_parts)

    return ParsedFile(
        path=path,
        language=language or "jupyter",
        kind="notebook",
        symbols=symbols,
        imports=imports,
        calls=calls,
        references=references,
        summary_hint=summary_hint,
    )
