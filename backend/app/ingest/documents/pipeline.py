"""Background processing pipeline for uploaded PDF documents."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import (
    get_document,
    get_session,
    save_document,
    save_document_chunks,
    save_document_pages,
)
from app.ingest.documents.pdf_parser import parse_pdf
from app.models import Document, DocumentChunk, DocumentPage
from app.rag.doc_chunker import chunk_document
from app.rag.doc_indexer import index_document_chunks
from app.rag.doc_summarizer import summarize_document

logger = logging.getLogger(__name__)


def _set_status(session: Session, doc: Document, status: str, error: Optional[str] = None) -> None:
    """Update and persist document status."""
    doc.status = status
    doc.error = error
    save_document(session, doc)
    logger.info("Document %s status -> %s", doc.id, status)


def run_document_pipeline(
    doc_id: str,
    embedder_fn: Optional[Callable[[list[str]], list[list[float]]]] = None,
) -> None:
    """Execute the extraction, chunking, indexing, and summarization pipeline for a document.

    Args:
        doc_id: The document UUID in the database.
        embedder_fn: Optional embedding function override (used in tests).
    """
    settings = get_settings()
    session = get_session()

    doc = get_document(session, doc_id)
    if not doc:
        logger.error("Document %s not found in database", doc_id)
        session.close()
        return

    stored_file_path = Path(settings.upload_dir) / doc.stored_name

    try:
        # 1. Extraction
        _set_status(session, doc, "extracting")
        parsed = parse_pdf(stored_file_path)

        # Persist extracted pages
        db_pages: list[DocumentPage] = [
            DocumentPage(
                document_id=doc.id,
                page_number=p.page_number,
                text=p.text,
                char_count=p.char_count,
            )
            for p in parsed.pages
        ]
        save_document_pages(session, db_pages)

        # Update metadata
        doc.page_count = len(parsed.pages)
        doc.outline_json = json.dumps(parsed.outline)
        doc.warnings_json = json.dumps(parsed.warnings)
        save_document(session, doc)

        # 2. Chunking
        _set_status(session, doc, "chunking")
        chunks = chunk_document(doc.id, doc.filename, parsed)
        save_document_chunks(session, chunks)

        # 3. Indexing
        _set_status(session, doc, "indexing")
        index_document_chunks(
            doc_id=doc.id,
            sha256=doc.sha256,
            filename=doc.filename,
            chunks=chunks,
            embedder_fn=embedder_fn,
        )
        doc.indexed = True
        doc.embedding_model = settings.embedding_model
        save_document(session, doc)

        # 4. Summarizing
        _set_status(session, doc, "summarizing")
        summary_dict = summarize_document(
            pages=db_pages,
            outline=parsed.outline,
            filename=doc.filename,
            doc_id=doc.id,
        )
        doc.summary_json = json.dumps(summary_dict)
        save_document(session, doc)

        # 5. Ready
        _set_status(session, doc, "ready")
        logger.info("Document %s processing successfully completed", doc.id)

    except Exception as exc:
        logger.error("Pipeline failed for document %s: %s", doc.id, exc, exc_info=True)
        _set_status(session, doc, "failed", error=str(exc))
    finally:
        session.close()
