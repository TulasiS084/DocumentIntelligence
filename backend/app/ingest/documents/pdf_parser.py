"""Page-by-page PDF extraction using pdfplumber with table, outline, and header/footer filtering."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pdfplumber

logger = logging.getLogger(__name__)

# Pattern for bare page number lines like "1", "Page 2", "Page 3 of 10", "4 / 12"
_PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page\s*)?\d+(?:\s*(?:of|\/)\s*\d+)?\s*$", re.IGNORECASE
)
_WHITESPACE_RE = re.compile(r"[ \t]+")
_NULL_CHAR_RE = re.compile(r"\x00")


@dataclass
class ExtractedTable:
    """A tabular data block extracted from a PDF page and rendered as Markdown."""

    page_number: int
    markdown: str
    section: Optional[str] = None


@dataclass
class ExtractedPage:
    """Cleaned text content of a single PDF page."""

    page_number: int  # 1-based
    text: str
    char_count: int
    section: Optional[str] = None


@dataclass
class ParsedPdfResult:
    """The aggregate parsing output for an entire PDF."""

    pages: list[ExtractedPage] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    outline: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def clean_text_line(line: str) -> str:
    """Strip null characters and collapse multiple horizontal spaces."""
    line = _NULL_CHAR_RE.sub("", line)
    line = _WHITESPACE_RE.sub(" ", line)
    return line.strip()


def table_to_markdown(table: list[list[Optional[str]]]) -> str:
    """Render a 2D grid of cell values into a standard GitHub Markdown table."""
    if not table:
        return ""

    cleaned_rows: list[list[str]] = []
    for row in table:
        cleaned_cells = [
            clean_text_line(str(cell or "").replace("\n", " "))
            for cell in row
        ]
        if any(cell for cell in cleaned_cells):
            cleaned_rows.append(cleaned_cells)

    if not cleaned_rows:
        return ""

    max_cols = max(len(row) for row in cleaned_rows)
    for row in cleaned_rows:
        while len(row) < max_cols:
            row.append("")

    header = cleaned_rows[0]
    separator = ["---"] * max_cols
    body = cleaned_rows[1:] if len(cleaned_rows) > 1 else []

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def filter_headers_and_footers(
    raw_pages_lines: list[list[str]],
    repeat_threshold: float = 0.6,
) -> list[list[str]]:
    """Remove repeating header and footer lines that occur on most pages, and bare page numbers.

    Args:
        raw_pages_lines: A list of line lists, one per page.
        repeat_threshold: Minimum fraction of pages a header/footer must appear on (default 0.6).

    Returns:
        Filtered lists of lines per page.
    """
    total_pages = len(raw_pages_lines)
    if total_pages == 0:
        return []

    # Count candidate top lines (first 2 lines) and bottom lines (last 2 lines)
    header_counts: dict[str, int] = {}
    footer_counts: dict[str, int] = {}

    if total_pages >= 3:
        for lines in raw_pages_lines:
            if not lines:
                continue
            for h in lines[:2]:
                norm_h = h.strip().lower()
                if len(norm_h) > 2 and not _PAGE_NUMBER_RE.match(h):
                    header_counts[norm_h] = header_counts.get(norm_h, 0) + 1

            for f in lines[-2:]:
                norm_f = f.strip().lower()
                if len(norm_f) > 2 and not _PAGE_NUMBER_RE.match(f):
                    footer_counts[norm_f] = footer_counts.get(norm_f, 0) + 1

    repeated_headers = {
        h for h, count in header_counts.items() if (count / total_pages) >= repeat_threshold
    }
    repeated_footers = {
        f for f, count in footer_counts.items() if (count / total_pages) >= repeat_threshold
    }

    filtered_pages: list[list[str]] = []
    for lines in raw_pages_lines:
        new_lines: list[str] = []
        n = len(lines)
        for idx, line in enumerate(lines):
            norm = line.strip().lower()
            # Drop bare page number lines anywhere
            if _PAGE_NUMBER_RE.match(line):
                continue
            # Drop repeating headers in top 3 lines
            if idx < 3 and norm in repeated_headers:
                continue
            # Drop repeating footers in bottom 3 lines
            if idx >= n - 3 and norm in repeated_footers:
                continue
            new_lines.append(line)
        filtered_pages.append(new_lines)

    return filtered_pages


def extract_outline(pdf: pdfplumber.PDF) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Extract bookmarks/outline from PDF and build a mapping from page number to section title.

    Returns:
        tuple of (outline_list, page_to_section_dict).
    """
    outline_list: list[dict[str, Any]] = []
    page_to_section: dict[int, str] = {}

    try:
        raw_outlines = list(pdf.doc.get_outlines())
    except Exception as exc:
        logger.debug("PDF outline extraction skipped or unsupported: %s", exc)
        return [], {}

    # Build page object ID -> 1-based page number map
    page_obj_to_num: dict[int, int] = {}
    for idx, page in enumerate(pdf.pages, start=1):
        page_obj = getattr(page, "page_obj", None)
        if page_obj is not None:
            obj_id = getattr(page_obj, "pageid", None)
            if obj_id is not None:
                page_obj_to_num[obj_id] = idx

    for item in raw_outlines:
        try:
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                continue
            level = item[0] if isinstance(item[0], int) else 1
            title = str(item[1]).strip()
            if not title:
                continue

            page_num: Optional[int] = None
            if len(item) > 2 and isinstance(item[2], list) and item[2]:
                ref = item[2][0]
                ref_id = getattr(ref, "objid", None)
                if ref_id in page_obj_to_num:
                    page_num = page_obj_to_num[ref_id]

            entry: dict[str, Any] = {"title": title, "level": level}
            if page_num is not None:
                entry["page"] = page_num
                if page_num not in page_to_section:
                    page_to_section[page_num] = title
            outline_list.append(entry)
        except Exception:
            continue

    return outline_list, page_to_section


def parse_pdf(file_path: Path | str) -> ParsedPdfResult:
    """Parse a PDF document page-by-page, extract text and tables, and filter repeated headers/footers.

    Args:
        file_path: Path to the PDF file on disk.

    Returns:
        ParsedPdfResult containing extracted pages, tables, outline, and warnings.

    Raises:
        ValueError: If all pages have virtually no extractable text (scanned PDF).
    """
    path = Path(file_path)
    result = ParsedPdfResult()

    with pdfplumber.open(path) as pdf:
        total_pages = len(pdf.pages)
        outline_list, page_to_section = extract_outline(pdf)
        result.outline = outline_list

        raw_pages_lines: list[list[str]] = []
        page_tables_map: dict[int, list[ExtractedTable]] = {}

        # First pass: extract raw text lines and tables per page
        for pno, page in enumerate(pdf.pages, start=1):
            try:
                # 1. Extract tables best-effort
                tables = page.extract_tables() or []
                for tbl in tables:
                    md_table = table_to_markdown(tbl)
                    if md_table.strip():
                        result.tables.append(
                            ExtractedTable(
                                page_number=pno,
                                markdown=md_table,
                            )
                        )

                # 2. Extract page text
                raw_text = page.extract_text() or ""
                lines = [
                    clean_text_line(line)
                    for line in raw_text.splitlines()
                    if clean_text_line(line)
                ]
                raw_pages_lines.append(lines)

            except Exception as page_exc:
                logger.warning("Error parsing page %d in %s: %s", pno, path.name, page_exc)
                result.warnings.append(f"Page {pno} failed to parse: {page_exc}")
                raw_pages_lines.append([])

        # Filter repeated headers and footers across all pages
        filtered_lines_per_page = filter_headers_and_footers(raw_pages_lines)

        # Second pass: assemble clean text, assign sections from outline, and check for sparse text
        current_section: Optional[str] = None
        pages_with_content = 0

        for pno, lines in enumerate(filtered_lines_per_page, start=1):
            if pno in page_to_section:
                current_section = page_to_section[pno]

            # Assign section to tables on this page
            for tbl in result.tables:
                if tbl.page_number == pno and tbl.section is None:
                    tbl.section = current_section

            page_text = "\n".join(lines).strip()
            char_count = len(page_text)

            if char_count < 20:
                result.warnings.append(
                    f"Page {pno} has almost no text ({char_count} chars); it may be scanned or blank."
                )
            else:
                pages_with_content += 1

            result.pages.append(
                ExtractedPage(
                    page_number=pno,
                    text=page_text,
                    char_count=char_count,
                    section=current_section,
                )
            )

        # Scanned PDF check: if ALL pages have virtually no text (< 20 chars) and no tables
        if pages_with_content == 0 and not result.tables:
            raise ValueError("This looks like a scanned PDF. OCR is not supported yet.")

    return result
