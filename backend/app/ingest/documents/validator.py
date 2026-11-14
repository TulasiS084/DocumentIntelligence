"""PDF upload validator: magic bytes, streaming size limiter, filename sanitizer, and integrity checks."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from pathlib import Path
from typing import BinaryIO, Optional

import pdfplumber
from fastapi import UploadFile

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._ -]")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class DocumentValidationError(Exception):
    """Raised when an uploaded document fails format, size, or integrity checks."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def sanitize_filename(raw_name: Optional[str], max_length: int = 128) -> str:
    """Sanitize display filename by stripping path traversals, separators, and control characters.

    Args:
        raw_name: The client-provided original filename.
        max_length: Maximum allowed filename length.

    Returns:
        A safe, clean display filename ending in .pdf.
    """
    if not raw_name:
        return "document.pdf"

    # Remove any directory path separators (POSIX or Windows)
    basename = raw_name.replace("\\", "/").split("/")[-1]
    # Remove control characters
    basename = _CONTROL_CHARS_RE.sub("", basename)
    # Strip dangerous characters and leading/trailing dots/spaces
    cleaned = _SAFE_FILENAME_RE.sub("", basename).strip(". ")

    if not cleaned:
        cleaned = "document"

    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"

    if len(cleaned) > max_length:
        stem = cleaned[:-4][: max_length - 4]
        cleaned = f"{stem}.pdf"

    return cleaned


def inspect_pdf_structure(file_path: Path, max_pages: int) -> int:
    """Open and inspect the PDF structure with pdfplumber.

    Verifies unencrypted status, non-zero page count, and page limit.

    Args:
        file_path: Path to the saved PDF file on disk.
        max_pages: Maximum permitted pages.

    Returns:
        Total page count.

    Raises:
        DocumentValidationError: If encrypted (422), corrupted (422), empty pages (422),
                                 or exceeds page limit (422).
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            # Check for encryption
            is_encrypted = getattr(pdf.doc, "is_encrypted", False)
            if is_encrypted:
                raise DocumentValidationError(
                    "PDF is password-protected or encrypted. Please upload an unencrypted PDF.",
                    status_code=422,
                )

            page_count = len(pdf.pages)
            if page_count == 0:
                raise DocumentValidationError(
                    "PDF file contains 0 pages.",
                    status_code=422,
                )

            if page_count > max_pages:
                raise DocumentValidationError(
                    f"PDF exceeds page limit ({page_count} > {max_pages} pages).",
                    status_code=422,
                )

            return page_count
    except DocumentValidationError:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        if "password" in msg or "encrypt" in msg:
            raise DocumentValidationError(
                "PDF is password-protected or encrypted. Please upload an unencrypted PDF.",
                status_code=422,
            ) from exc
        logger.warning("Corrupted or unreadable PDF: %s (%s)", file_path, exc)
        raise DocumentValidationError(
            f"PDF file is corrupted or cannot be read: {exc}",
            status_code=422,
        ) from exc


async def stream_and_validate_upload(
    upload_file: UploadFile,
    upload_dir: str,
    max_bytes: int,
    max_pages: int,
) -> tuple[str, str, int, str, int]:
    """Stream an uploaded file to disk while validating magic bytes and size limit.

    Args:
        upload_file: The FastAPI UploadFile instance.
        upload_dir: Directory where sanitized UUID files are stored.
        max_bytes: Maximum allowed bytes per file.
        max_pages: Maximum allowed PDF pages.

    Returns:
        tuple of (sanitized_filename, stored_name, size_bytes, sha256_hex, page_count).

    Raises:
        DocumentValidationError: On invalid type, empty file, oversize, encryption, or corruption.
    """
    target_dir = Path(upload_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    sanitized_name = sanitize_filename(upload_file.filename)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    stored_path = target_dir / stored_name

    hasher = hashlib.sha256()
    total_bytes = 0
    chunk_size = 64 * 1024  # 64 KB streaming buffer
    first_chunk = True

    try:
        with open(stored_path, "wb") as out_fh:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break

                if first_chunk:
                    first_chunk = False
                    if len(chunk) == 0:
                        raise DocumentValidationError(
                            "Uploaded file is empty (0 bytes).",
                            status_code=400,
                        )
                    if not chunk.startswith(PDF_MAGIC):
                        raise DocumentValidationError(
                            "Invalid file type: file must be a valid PDF (missing %PDF- header).",
                            status_code=400,
                        )

                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    max_mb = max_bytes // (1024 * 1024)
                    raise DocumentValidationError(
                        f"File exceeds maximum upload size of {max_mb} MB.",
                        status_code=413,
                    )

                hasher.update(chunk)
                out_fh.write(chunk)

        if total_bytes == 0:
            raise DocumentValidationError(
                "Uploaded file is empty (0 bytes).",
                status_code=400,
            )

        # Inspect PDF page count and structure
        page_count = inspect_pdf_structure(stored_path, max_pages)
        sha256_hex = hasher.hexdigest()

        return sanitized_name, stored_name, total_bytes, sha256_hex, page_count

    except Exception:
        # Guarantee cleanup if validation fails at any point
        if stored_path.exists():
            try:
                os.remove(stored_path)
            except OSError:
                pass
        raise
