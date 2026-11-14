"""Tests for PDF document indexing and retrieval."""

import math
from app.models import DocumentChunk
from app.rag.doc_indexer import index_document_chunks, delete_document_index
from app.rag.retriever import retrieve_document, retrieve_source


VOCAB = [
    "oauth2", "authentication", "bearer", "tokens",
    "postgresql", "connection", "pool", "max",
    "redis", "postgres", "service", "port", "ports", "table",
    "user", "system", "server", "configuration"
]


def _fake_embed(text: str) -> list[float]:
    """Bag-of-words embedding vector over VOCAB for deterministic testing."""
    text_lower = text.lower()
    vec = [float(text_lower.count(w)) for w in VOCAB]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _fake_embed_batch(texts: list[str]) -> list[list[float]]:
    return [_fake_embed(t) for t in texts]


def test_doc_retrieval_and_filtering():
    doc_id = "test-doc-search"
    sha256 = "abcdef1234567890"
    filename = "system_manual.pdf"

    chunks = [
        DocumentChunk(
            id="c1",
            document_id=doc_id,
            chunk_id=f"{doc_id}:0",
            page_start=1,
            page_end=1,
            section="Authentication",
            kind="text",
            chunk_index=0,
            text="User authentication requires bearer tokens issued by OAuth2 server.",
            embed_text=f"{filename} > Authentication (p. 1)\n\nUser authentication requires bearer tokens issued by OAuth2 server.",
        ),
        DocumentChunk(
            id="c2",
            document_id=doc_id,
            chunk_id=f"{doc_id}:1",
            page_start=2,
            page_end=2,
            section="Database",
            kind="text",
            chunk_index=1,
            text="PostgreSQL connection pool max size is configured to 50 connections.",
            embed_text=f"{filename} > Database (p. 2)\n\nPostgreSQL connection pool max size is configured to 50 connections.",
        ),
        DocumentChunk(
            id="c3",
            document_id=doc_id,
            chunk_id=f"{doc_id}:2",
            page_start=3,
            page_end=3,
            section="Network Ports",
            kind="table",
            chunk_index=2,
            text="| Service | Port |\n| --- | --- |\n| Redis | 6379 |\n| Postgres | 5432 |",
            embed_text=f"{filename} > Network Ports (p. 3)\n\n| Service | Port |\n| --- | --- |\n| Redis | 6379 |\n| Postgres | 5432 |",
        ),
    ]

    index_document_chunks(
        doc_id=doc_id,
        sha256=sha256,
        filename=filename,
        chunks=chunks,
        embedder_fn=_fake_embed_batch,
    )

    # 1. Search for authentication -> should match page 1
    results, conf = retrieve_document(
        doc_id=doc_id,
        query="OAuth2 authentication bearer tokens",
        mode="hybrid",
        top_k=3,
        embedder_fn=_fake_embed,
    )
    assert len(results) >= 1
    assert results[0].page_start == 1
    assert "OAuth2" in results[0].text
    assert conf > 0.0

    # 2. Universal retrieve_source with doc:doc_id
    src_results, src_conf = retrieve_source(
        source=f"doc:{doc_id}",
        query="PostgreSQL connection pool",
        mode="hybrid",
        top_k=2,
        embedder_fn=_fake_embed,
    )
    assert len(src_results) >= 1
    assert src_results[0].page_start == 2

    # 3. Filter by kind='table'
    tbl_results, _ = retrieve_document(
        doc_id=doc_id,
        query="Redis Postgres ports",
        mode="hybrid",
        filters={"kind": "table"},
        embedder_fn=_fake_embed,
    )
    assert len(tbl_results) == 1
    assert tbl_results[0].kind == "table"
    assert tbl_results[0].page_start == 3

    # 4. Filter by page_num
    p2_results, _ = retrieve_document(
        doc_id=doc_id,
        query="server configuration",
        mode="bm25",
        filters={"page_num": 2},
    )
    assert all(r.page_start <= 2 <= r.page_end for r in p2_results)

    # 5. Clean up indices
    delete_document_index(doc_id, sha256)
