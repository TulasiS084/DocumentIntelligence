"""Indexing adapter for PDF documents with BM25, in-memory vectors, and ChromaDB."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from app.config import get_settings
from app.models import DocumentChunk
from app.rag.indexer import (
    bm25_cache,
    get_chroma_client,
    tokenize_code,
    vector_cache,
)

logger = logging.getLogger(__name__)


def sanitize_doc_collection_name(doc_id: str, sha256: str) -> str:
    """Create a Chroma-compliant collection name for a document."""
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)[:24]
    clean_sha = re.sub(r"[^a-zA-Z0-9_-]", "", sha256)[:8]
    name = f"doc_{clean_id}_{clean_sha}"
    if len(name) < 3:
        name = f"col_{name}"
    if len(name) > 63:
        name = name[:63]
    if not name[0].isalnum():
        name = "d" + name[1:]
    if not name[-1].isalnum():
        name = name[:-1] + "0"
    return name


def index_document_chunks(
    doc_id: str,
    sha256: str,
    filename: str,
    chunks: list[DocumentChunk],
    embedder_fn: Optional[Callable[[list[str]], list[list[float]]]] = None,
) -> None:
    """Index document chunks into BM25, in-memory vector cache, and ChromaDB.

    Args:
        doc_id: UUID of the document.
        sha256: SHA-256 hex digest of the document.
        filename: Display filename.
        chunks: List of DocumentChunk models.
        embedder_fn: Optional embedding callable, defaults to embedder.embed_texts.
    """
    if not chunks:
        logger.info("No chunks to index for document %s", doc_id)
        return

    settings = get_settings()
    source_key = f"doc:{doc_id}"

    # 1. Build and cache BM25 Index
    try:
        from rank_bm25 import BM25Plus

        tokenized_corpus = [tokenize_code(chunk.embed_text) for chunk in chunks]
        bm25_index = BM25Plus(tokenized_corpus)
        chunk_metas = [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": doc_id,
                "filename": filename,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": chunk.section or "",
                "kind": chunk.kind,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
            }
            for chunk in chunks
        ]
        bm25_cache.put(source_key, bm25_index, chunk_metas)
        logger.info("BM25 index built for document %s with %d chunks", doc_id, len(chunks))
    except Exception as e:
        logger.error("Failed to build BM25 index for document %s: %s", doc_id, e, exc_info=True)

    # 2. Embedding generation & Vector caching
    chunk_metas = [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": doc_id,
            "filename": filename,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "section": chunk.section or "",
            "kind": chunk.kind,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
        }
        for chunk in chunks
    ]
    all_embeddings: list[list[float]] = []
    try:
        if embedder_fn is None:
            from app.rag.embedder import embed_texts

            embedder_fn = embed_texts

        texts = [c.embed_text for c in chunks]
        all_embeddings = embedder_fn(texts)
        vector_cache.put(
            source_key,
            list(zip(chunk_metas, all_embeddings)),
            embedding_model=settings.embedding_model,
        )
    except Exception as e:
        logger.warning("Embedding generation encountered issue for document %s: %s", doc_id, e)

    # 3. ChromaDB collection
    try:
        client = get_chroma_client()
        col_name = sanitize_doc_collection_name(doc_id, sha256)

        try:
            client.delete_collection(col_name)
        except Exception:
            pass

        collection = client.create_collection(
            name=col_name,
            metadata={
                "document_id": doc_id,
                "sha256": sha256,
                "filename": filename,
                "embedding_model": settings.embedding_model,
            },
        )

        batch_size = 64
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            batch_embs = (
                all_embeddings[i : i + batch_size]
                if all_embeddings
                else embedder_fn([c.embed_text for c in batch])
            )
            ids = [f"{doc_id}_{c.chunk_index}" for c in batch]
            metadatas = [
                {
                    "document_id": doc_id,
                    "chunk_id": c.chunk_id,
                    "filename": filename,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                    "section": c.section or "",
                    "kind": c.kind,
                    "chunk_index": c.chunk_index,
                }
                for c in batch
            ]
            collection.add(
                ids=ids,
                documents=[c.text for c in batch],
                embeddings=batch_embs,
                metadatas=metadatas,
            )

        logger.info(
            "ChromaDB collection '%s' created with %d chunks for document %s",
            col_name,
            len(chunks),
            doc_id,
        )
    except Exception as e:
        logger.info(
            "ChromaDB collection skipped or unavailable for doc %s (%s); using in-memory vector cache",
            doc_id,
            e,
        )


def delete_document_index(doc_id: str, sha256: Optional[str] = None) -> None:
    """Clear BM25, in-memory vectors, and Chroma collection for a document."""
    source_key = f"doc:{doc_id}"

    # Clear caches
    try:
        if source_key in bm25_cache._cache:
            del bm25_cache._cache[source_key]
    except Exception:
        pass

    try:
        if source_key in vector_cache._cache:
            del vector_cache._cache[source_key]
    except Exception:
        pass

    # Delete ChromaDB collection
    if sha256:
        try:
            client = get_chroma_client()
            col_name = sanitize_doc_collection_name(doc_id, sha256)
            client.delete_collection(col_name)
        except Exception:
            pass
