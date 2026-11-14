"""Page-boundary semantic chunker for PDF documents with table separation and short-page merging."""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.ingest.documents.pdf_parser import ExtractedPage, ExtractedTable, ParsedPdfResult
from app.models import DocumentChunk

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving punctuation."""
    sentences = _SENTENCE_SPLIT_RE.split(text)
    return [s.strip() for s in sentences if s.strip()]


def _chunk_text_window(
    text: str,
    target_words: int = 250,
    max_words: int = 300,
    overlap_words: int = 40,
) -> list[str]:
    """Chunk a long block of text into ~200-300 word pieces with ~40 words overlap."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    # Flatten into sentence units (or word blocks if no punctuation)
    units: list[str] = []
    for p in paragraphs:
        p_words = p.split()
        if len(p_words) <= max_words:
            units.append(p)
        else:
            sentences = _split_into_sentences(p)
            for s in (sentences if sentences else [p]):
                s_words = s.split()
                if len(s_words) <= max_words:
                    units.append(s)
                else:
                    for w_idx in range(0, len(s_words), max_words - overlap_words):
                        slice_words = s_words[w_idx : w_idx + max_words]
                        if slice_words:
                            units.append(" ".join(slice_words))

    if not units:
        return [text] if text.strip() else []

    chunks: list[str] = []
    current_unit_idx = 0
    total_units = len(units)

    while current_unit_idx < total_units:
        accumulated_units: list[str] = []
        current_words: list[str] = []

        idx = current_unit_idx
        while idx < total_units:
            unit = units[idx]
            u_words = unit.split()
            if current_words and (len(current_words) + len(u_words) > max_words):
                break
            accumulated_units.append(unit)
            current_words.extend(u_words)
            idx += 1

        if not accumulated_units:
            accumulated_units.append(units[current_unit_idx])
            idx = current_unit_idx + 1

        chunk_str = "\n\n".join(accumulated_units)
        chunks.append(chunk_str)

        if idx >= total_units:
            break

        # Calculate overlap step: step forward until we retain approximately overlap_words
        step_forward = max(1, len(accumulated_units) - 1)
        # Advance by at least 1 unit
        current_unit_idx += step_forward

    return chunks


def _format_embed_text(
    filename: str,
    section: Optional[str],
    page_start: int,
    page_end: int,
    text: str,
) -> str:
    """Format chunk text for embedding with context prefix: filename > section (p. N)."""
    page_label = f"p. {page_start}" if page_start == page_end else f"p. {page_start}-{page_end}"
    if section and section.strip():
        header = f"{filename} > {section.strip()} ({page_label})"
    else:
        header = f"{filename} ({page_label})"
    return f"{header}\n\n{text}".strip()


def chunk_document(
    document_id: str,
    filename: str,
    parsed: ParsedPdfResult,
) -> list[DocumentChunk]:
    """Convert parsed PDF pages and tables into semantic DocumentChunk models.

    Args:
        document_id: The UUID of the document.
        filename: Sanitized original filename.
        parsed: The ParsedPdfResult from pdf_parser.

    Returns:
        List of DocumentChunk models ready for database storage and indexing.
    """
    chunks: list[DocumentChunk] = []
    chunk_index = 0

    # 1. Merge short pages (< 100 words) with subsequent page
    merged_pages: list[dict] = []
    i = 0
    total_pages = len(parsed.pages)

    while i < total_pages:
        page = parsed.pages[i]
        p_text = page.text.strip()
        words = p_text.split()
        page_start = page.page_number
        page_end = page.page_number
        section = page.section

        # If short and next page exists, merge
        while len(words) < 100 and (i + 1) < total_pages:
            i += 1
            next_page = parsed.pages[i]
            next_text = next_page.text.strip()
            if next_text:
                p_text = f"{p_text}\n\n{next_text}".strip()
                words = p_text.split()
            page_end = next_page.page_number
            if not section and next_page.section:
                section = next_page.section
            # Stop merging once we have enough words
            if len(words) >= 100:
                break

        if p_text:
            merged_pages.append(
                {
                    "page_start": page_start,
                    "page_end": page_end,
                    "section": section,
                    "text": p_text,
                }
            )
        i += 1

    # 2. Chunk merged pages into ~200-300 word windows
    for mp in merged_pages:
        text = mp["text"]
        words = text.split()
        p_start = mp["page_start"]
        p_end = mp["page_end"]
        sec = mp["section"]

        if len(words) <= 300:
            text_blocks = [text]
        else:
            text_blocks = _chunk_text_window(text, target_words=250, max_words=300, overlap_words=40)

        for blk in text_blocks:
            c_id = f"{document_id}:{chunk_index}"
            embed_text = _format_embed_text(filename, sec, p_start, p_end, blk)
            chunks.append(
                DocumentChunk(
                    document_id=document_id,
                    chunk_id=c_id,
                    page_start=p_start,
                    page_end=p_end,
                    section=sec,
                    kind="text",
                    chunk_index=chunk_index,
                    text=blk,
                    embed_text=embed_text,
                )
            )
            chunk_index += 1

    # 3. Add table chunks (kept separate, kind='table')
    for tbl in parsed.tables:
        c_id = f"{document_id}:{chunk_index}"
        embed_text = _format_embed_text(
            filename,
            tbl.section,
            tbl.page_number,
            tbl.page_number,
            tbl.markdown,
        )
        chunks.append(
            DocumentChunk(
                document_id=document_id,
                chunk_id=c_id,
                page_start=tbl.page_number,
                page_end=tbl.page_number,
                section=tbl.section,
                kind="table",
                chunk_index=chunk_index,
                text=tbl.markdown,
                embed_text=embed_text,
            )
        )
        chunk_index += 1

    return chunks
