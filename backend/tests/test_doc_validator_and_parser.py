"""Tests for PDF upload validation and page-by-page parsing."""

import asyncio
import io
from pathlib import Path
import pytest
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from starlette.datastructures import Headers, UploadFile

from app.ingest.documents.validator import (
    DocumentValidationError,
    sanitize_filename,
    stream_and_validate_upload,
    inspect_pdf_structure,
)
from app.ingest.documents.pdf_parser import (
    filter_headers_and_footers,
    parse_pdf,
    table_to_markdown,
)


def create_simple_pdf_bytes(
    page_texts: list[str],
    repeated_header: str | None = None,
    repeated_footer: str | None = None,
    outline_entries: list[tuple[str, int]] | None = None,
) -> bytes:
    """Generate in-memory PDF bytes with reportlab."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    for idx, text in enumerate(page_texts, start=1):
        if outline_entries:
            for title, pno in outline_entries:
                if pno == idx:
                    c.bookmarkPage(f"p_{idx}")
                    c.addOutlineEntry(title, f"p_{idx}")

        # Draw repeated header
        if repeated_header:
            c.drawString(100, 750, repeated_header)

        # Draw page body text
        y = 700
        for line in text.split("\n"):
            c.drawString(100, y, line)
            y -= 20

        # Draw repeated footer and page number
        if repeated_footer:
            c.drawString(100, 60, repeated_footer)
        c.drawString(500, 40, f"Page {idx}")

        c.showPage()

    c.save()
    return buf.getvalue()


def create_table_pdf_bytes() -> bytes:
    """Generate in-memory PDF bytes with a table using Platypus."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    elements = []

    data = [
        ["Service", "Port", "Protocol"],
        ["API Gateway", "8000", "HTTP"],
        ["Database", "5432", "Postgres"],
        ["Cache", "6379", "Redis"],
    ]
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    elements.append(t)
    doc.build(elements)
    return buf.getvalue()


# ── Validator Tests ───────────────────────────────────────────────────────


def test_sanitize_filename():
    assert sanitize_filename("normal_doc.pdf") == "normal_doc.pdf"
    assert sanitize_filename("../../../etc/passwd") == "passwd.pdf"
    assert sanitize_filename("..\\..\\windows\\system32.pdf") == "system32.pdf"
    assert sanitize_filename("cool document (v2) [draft]!.pdf") == "cool document v2 draft.pdf"
    assert sanitize_filename("") == "document.pdf"
    assert sanitize_filename(None) == "document.pdf"


def test_validator_valid_pdf(tmp_path: Path):
    async def _run():
        pdf_bytes = create_simple_pdf_bytes(["This is valid page one.", "This is valid page two."])
        upload = UploadFile(
            file=io.BytesIO(pdf_bytes),
            filename="report.pdf",
            headers=Headers({"content-type": "application/pdf"}),
        )

        sanitized, stored, size, sha256_hex, page_count = await stream_and_validate_upload(
            upload, str(tmp_path), max_bytes=1024 * 1024, max_pages=10
        )

        assert sanitized == "report.pdf"
        assert stored.endswith(".pdf")
        assert size == len(pdf_bytes)
        assert len(sha256_hex) == 64
        assert page_count == 2
        assert (tmp_path / stored).exists()

    asyncio.run(_run())


def test_validator_wrong_magic_bytes_rejected(tmp_path: Path):
    async def _run():
        fake_pdf = b"NOT A PDF CONTENT AT ALL"
        upload = UploadFile(file=io.BytesIO(fake_pdf), filename="trick.pdf")

        with pytest.raises(DocumentValidationError) as exc_info:
            await stream_and_validate_upload(upload, str(tmp_path), max_bytes=1024 * 1024, max_pages=10)

        assert exc_info.value.status_code == 400
        assert "missing %PDF- header" in exc_info.value.message

    asyncio.run(_run())


def test_validator_empty_file_rejected(tmp_path: Path):
    async def _run():
        upload = UploadFile(file=io.BytesIO(b""), filename="empty.pdf")

        with pytest.raises(DocumentValidationError) as exc_info:
            await stream_and_validate_upload(upload, str(tmp_path), max_bytes=1024 * 1024, max_pages=10)

        assert exc_info.value.status_code == 400
        assert "empty" in exc_info.value.message.lower()

    asyncio.run(_run())


def test_validator_oversized_file_rejected(tmp_path: Path):
    async def _run():
        large_pdf = b"%PDF-1.4\n" + b"X" * 2000
        upload = UploadFile(file=io.BytesIO(large_pdf), filename="huge.pdf")

        with pytest.raises(DocumentValidationError) as exc_info:
            await stream_and_validate_upload(upload, str(tmp_path), max_bytes=500, max_pages=10)

        assert exc_info.value.status_code == 413
        assert "maximum upload size" in exc_info.value.message
        assert len(list(tmp_path.glob("*.pdf"))) == 0

    asyncio.run(_run())


def test_validator_too_many_pages_rejected(tmp_path: Path):
    async def _run():
        pdf_bytes = create_simple_pdf_bytes(["Page 1", "Page 2", "Page 3"])
        upload = UploadFile(file=io.BytesIO(pdf_bytes), filename="long.pdf")

        with pytest.raises(DocumentValidationError) as exc_info:
            await stream_and_validate_upload(upload, str(tmp_path), max_bytes=1024 * 1024, max_pages=2)

        assert exc_info.value.status_code == 422
        assert "exceeds page limit" in exc_info.value.message

    asyncio.run(_run())


def test_validator_corrupted_pdf_rejected(tmp_path: Path):
    async def _run():
        corrupted = b"%PDF-1.4\nCorrupted binary junk \xff\xfe\x00..."
        upload = UploadFile(file=io.BytesIO(corrupted), filename="broken.pdf")

        with pytest.raises(DocumentValidationError) as exc_info:
            await stream_and_validate_upload(upload, str(tmp_path), max_bytes=1024 * 1024, max_pages=10)

        assert exc_info.value.status_code == 422
        assert "corrupted" in exc_info.value.message.lower()

    asyncio.run(_run())


# ── Parser Tests ─────────────────────────────────────────────────────────


def test_parser_multi_page_and_headers_removed(tmp_path: Path):
    header = "ACME Corporation Confidential Architecture"
    footer = "Internal Distribution Only"
    page_texts = [
        "First chapter introduces the overall distributed architecture of RepoLens.",
        "Second chapter details the tree-sitter parser modules and symbol graphing.",
        "Third chapter provides performance benchmarks and retrieval evaluation.",
        "Fourth chapter discusses deployment and security safeguards in production.",
    ]
    pdf_bytes = create_simple_pdf_bytes(
        page_texts,
        repeated_header=header,
        repeated_footer=footer,
        outline_entries=[("Overview", 1), ("Parsing", 2)],
    )
    test_pdf = tmp_path / "doc.pdf"
    test_pdf.write_bytes(pdf_bytes)

    res = parse_pdf(test_pdf)
    assert len(res.pages) == 4
    assert res.pages[0].section == "Overview"
    assert res.pages[1].section == "Parsing"

    # Verify that repeated header & footer lines were stripped from the text
    for page in res.pages:
        assert header not in page.text
        assert footer not in page.text
        assert "Page " not in page.text


def test_parser_table_extraction(tmp_path: Path):
    pdf_bytes = create_table_pdf_bytes()
    test_pdf = tmp_path / "table.pdf"
    test_pdf.write_bytes(pdf_bytes)

    res = parse_pdf(test_pdf)
    assert len(res.tables) >= 1
    tbl = res.tables[0]
    assert tbl.page_number == 1
    assert "| Service | Port | Protocol |" in tbl.markdown
    assert "| API Gateway | 8000 | HTTP |" in tbl.markdown


def test_parser_warning_on_sparse_page(tmp_path: Path):
    # Page 1 has plenty of text, Page 2 has almost none (e.g. 5 chars)
    page_texts = [
        "This page contains substantial explanatory documentation about the system.",
        "Hi.",
    ]
    pdf_bytes = create_simple_pdf_bytes(page_texts)
    test_pdf = tmp_path / "sparse.pdf"
    test_pdf.write_bytes(pdf_bytes)

    res = parse_pdf(test_pdf)
    assert len(res.pages) == 2
    assert any("Page 2 has almost no text" in w for w in res.warnings)


def test_parser_scanned_pdf_fails(tmp_path: Path):
    # All pages have no or < 20 chars of text
    page_texts = ["", " "]
    pdf_bytes = create_simple_pdf_bytes(page_texts)
    test_pdf = tmp_path / "scanned.pdf"
    test_pdf.write_bytes(pdf_bytes)

    with pytest.raises(ValueError) as exc_info:
        parse_pdf(test_pdf)

    assert "This looks like a scanned PDF. OCR is not supported yet." in str(exc_info.value)
