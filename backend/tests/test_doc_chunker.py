"""Tests for document chunking, short-page merging, and table preservation."""

from app.ingest.documents.pdf_parser import ExtractedPage, ExtractedTable, ParsedPdfResult
from app.rag.doc_chunker import chunk_document


def test_chunk_page_numbers_accurate():
    pages = [
        ExtractedPage(
            page_number=1,
            text="This is an extensive first page describing the software design principles. " * 15,
            char_count=1000,
            section="Intro",
        ),
        ExtractedPage(
            page_number=2,
            text="This is an extensive second page describing the database schema and storage. " * 15,
            char_count=1000,
            section="Database",
        ),
    ]
    parsed = ParsedPdfResult(pages=pages)
    chunks = chunk_document("doc-123", "architecture.pdf", parsed)

    assert len(chunks) >= 2
    # First chunk belongs to page 1
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 1
    assert chunks[0].section == "Intro"
    assert "architecture.pdf > Intro (p. 1)" in chunks[0].embed_text


def test_chunk_short_pages_merge():
    # Page 1 has 5 words (< 100 words), Page 2 has 8 words (< 100 words), Page 3 has 150 words
    pages = [
        ExtractedPage(page_number=1, text="Title: System Overview Document", char_count=30),
        ExtractedPage(page_number=2, text="Confidential internal engineering report.", char_count=40),
        ExtractedPage(
            page_number=3,
            text="Here is the main text of the report. " * 25,
            char_count=800,
            section="Main",
        ),
    ]
    parsed = ParsedPdfResult(pages=pages)
    chunks = chunk_document("doc-456", "overview.pdf", parsed)

    # The short pages 1 & 2 should merge into page 3
    first_chunk = chunks[0]
    assert first_chunk.page_start == 1
    assert first_chunk.page_end == 3
    assert "Title: System Overview Document" in first_chunk.text
    assert "Confidential internal engineering report." in first_chunk.text


def test_chunk_overlap():
    # Long text with over 400 words
    words = [f"word{i}" for i in range(500)]
    long_text = " ".join(words)
    pages = [
        ExtractedPage(page_number=1, text=long_text, char_count=len(long_text)),
    ]
    parsed = ParsedPdfResult(pages=pages)
    chunks = chunk_document("doc-789", "data.pdf", parsed)

    assert len(chunks) >= 2
    # Ensure chunk 1 and chunk 2 have overlapping content
    chunk_1_words = set(chunks[0].text.split())
    chunk_2_words = set(chunks[1].text.split())
    common = chunk_1_words.intersection(chunk_2_words)
    assert len(common) > 10


def test_tables_stay_separate():
    pages = [
        ExtractedPage(page_number=1, text="Text description of ports and protocols." * 10, char_count=400),
    ]
    tables = [
        ExtractedTable(
            page_number=1,
            markdown="| Service | Port |\n| --- | --- |\n| API | 8000 |",
            section="Ports",
        )
    ]
    parsed = ParsedPdfResult(pages=pages, tables=tables)
    chunks = chunk_document("doc-tbl", "spec.pdf", parsed)

    table_chunks = [c for c in chunks if c.kind == "table"]
    text_chunks = [c for c in chunks if c.kind == "text"]

    assert len(table_chunks) == 1
    assert len(text_chunks) == 1
    assert table_chunks[0].kind == "table"
    assert "| Service | Port |" in table_chunks[0].text
    assert table_chunks[0].page_start == 1
