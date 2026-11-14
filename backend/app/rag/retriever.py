"""Hybrid retrieval combining ChromaDB vector search and BM25 with Reciprocal Rank Fusion."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from app.config import get_settings
from app.models import DocumentSearchResultItem, SearchResultItem
from app.rag.indexer import (
    bm25_cache,
    get_chroma_client,
    sanitize_collection_name,
    tokenize_code,
    vector_cache,
)

logger = logging.getLogger(__name__)


def _make_snippet(text: str, max_lines: int = 10, max_chars: int = 400) -> str:
    """Extract a concise readable preview snippet from code/doc chunk text."""
    if not text:
        return ""
    lines = text.splitlines()[:max_lines]
    joined = "\n".join(lines)
    if len(joined) > max_chars:
        return joined[:max_chars].rstrip() + "..."
    return joined


def _matches_filters(item: dict[str, Any], filters: Optional[dict[str, Any]]) -> bool:
    """Check if item metadata satisfies optional query filters."""
    if not filters:
        return True
    for key, val in filters.items():
        if val is None:
            continue
        item_val = item.get(key)
        if isinstance(val, list):
            if item_val not in val:
                return False
        elif isinstance(val, str):
            if key == "path":
                if not str(item_val).startswith(val):
                    return False
            elif str(item_val).lower() != str(val).lower():
                return False
        elif item_val != val:
            return False
    return True


def retrieve(
    repo_id: str,
    query: str,
    mode: str = "hybrid",
    top_k: int = 6,
    filters: Optional[dict[str, Any]] = None,
    commit_sha: Optional[str] = None,
    embedder_fn: Optional[Callable[[str], list[float]]] = None,
) -> tuple[list[SearchResultItem], float]:
    """Retrieve relevant code and documentation chunks.

    Modes:
        - "vector": Dense cosine similarity via ChromaDB.
        - "bm25": Sparse keyword matching via BM25Okapi with code tokenizer.
        - "hybrid": Reciprocal Rank Fusion (RRF) combining vector and BM25.

    Confidence Score Formula:
        For vector: cosine similarity sim = max(0.0, 1.0 - (dist / 2.0)).
        For BM25: normalized BM25 score = top_bm25 / (top_bm25 + 10.0).
        For hybrid: 0.6 * sim + 0.4 * bm25_norm.
        Clamped to [0.0, 1.0]. If 0 results, confidence = 0.0.

    Returns:
        tuple of (list of SearchResultItem, overall confidence score [0.0, 1.0]).
    """
    settings = get_settings()
    top_k_each = settings.retrieval_top_k_each
    rrf_k = settings.rrf_k

    vector_ranked: list[dict[str, Any]] = []
    vector_distances: list[float] = []
    bm25_ranked: list[dict[str, Any]] = []
    bm25_scores: list[float] = []

    # 1. Vector Search
    if mode in ("vector", "hybrid"):
        q_embedding: Optional[list[float]] = None
        try:
            if embedder_fn is None:
                from app.rag.embedder import embed_query
                embedder_fn = embed_query
            q_embedding = embedder_fn(query)
        except Exception as e:
            logger.warning("Vector query embedding failed: %s", e)

        if q_embedding:
            # Try ChromaDB first
            try:
                client = get_chroma_client()
                col_name = sanitize_collection_name(repo_id, commit_sha)
                collection = client.get_collection(col_name)

                query_res = collection.query(
                    query_embeddings=[q_embedding],
                    n_results=min(top_k_each * 2, max(collection.count(), 1)),
                    include=["metadatas", "documents", "distances"],
                )

                if query_res and query_res["ids"] and query_res["ids"][0]:
                    ids = query_res["ids"][0]
                    docs = query_res["documents"][0] if query_res["documents"] else [""] * len(ids)
                    metas = query_res["metadatas"][0] if query_res["metadatas"] else [{}] * len(ids)
                    dists = query_res["distances"][0] if query_res["distances"] else [1.0] * len(ids)

                    for cid, doc, meta, dist in zip(ids, docs, metas, dists):
                        item = dict(meta)
                        item["text"] = doc
                        if _matches_filters(item, filters):
                            vector_ranked.append(item)
                            vector_distances.append(dist)
                            if len(vector_ranked) >= top_k_each:
                                break
            except Exception as e:
                logger.debug("ChromaDB vector retrieval skipped/failed: %s", e)

            # Fallback to in-memory vector cache if ChromaDB returned no results or is unavailable
            if not vector_ranked:
                cached_vecs = vector_cache.get(repo_id, required_model=settings.embedding_model)
                if cached_vecs:
                    scored_items = []
                    for item, emb in cached_vecs:
                        if _matches_filters(item, filters):
                            sim = sum(a * b for a, b in zip(q_embedding, emb))
                            dist = max(0.0, 1.0 - sim) * 2.0
                            scored_items.append((sim, dist, item))
                    scored_items.sort(key=lambda x: x[0], reverse=True)
                    for _, dist, item in scored_items[:top_k_each]:
                        vector_ranked.append(item)
                        vector_distances.append(dist)

    # 2. BM25 Search
    if mode in ("bm25", "hybrid"):
        cached = bm25_cache.get(repo_id)
        if cached:
            bm25_obj, chunk_metas = cached
            tokenized_query = tokenize_code(query)
            if tokenized_query:
                scores = bm25_obj.get_scores(tokenized_query)
                scored_indices = sorted(
                    range(len(scores)), key=lambda i: scores[i], reverse=True
                )
                for idx in scored_indices:
                    score = float(scores[idx])
                    if score <= 0.0:
                        break
                    item = dict(chunk_metas[idx])
                    if _matches_filters(item, filters):
                        bm25_ranked.append(item)
                        bm25_scores.append(score)
                        if len(bm25_ranked) >= top_k_each:
                            break

    # Calculate confidence indicators
    top_vector_sim = 0.0
    if vector_distances:
        # Chroma cosine distance is typically 1 - cosine_similarity, bounded [0, 2]
        top_dist = max(0.0, min(vector_distances[0], 2.0))
        top_vector_sim = max(0.0, 1.0 - (top_dist / 2.0))

    top_bm25_norm = 0.0
    if bm25_scores:
        top_bm25_norm = min(1.0, bm25_scores[0] / (bm25_scores[0] + 10.0))

    # 3. Combine / Rank
    if mode == "vector":
        confidence = round(top_vector_sim, 3)
        results: list[SearchResultItem] = []
        for rank, (item, dist) in enumerate(zip(vector_ranked[:top_k], vector_distances[:top_k]), start=1):
            sim = max(0.0, 1.0 - (min(dist, 2.0) / 2.0))
            results.append(
                SearchResultItem(
                    chunk_id=str(item.get("chunk_id", "")),
                    path=str(item.get("path", "")),
                    language=item.get("language") or None,
                    kind=str(item.get("kind", "code")),
                    symbol_name=item.get("symbol_name") or None,
                    start_line=int(item.get("start_line", 1)),
                    end_line=int(item.get("end_line", 1)),
                    snippet=_make_snippet(str(item.get("text", ""))),
                    score=round(sim, 4),
                    vector_rank=rank,
                    bm25_rank=None,
                )
            )
        return results, confidence

    if mode == "bm25":
        confidence = round(top_bm25_norm, 3)
        results = []
        for rank, (item, score) in enumerate(zip(bm25_ranked[:top_k], bm25_scores[:top_k]), start=1):
            results.append(
                SearchResultItem(
                    chunk_id=str(item.get("chunk_id", "")),
                    path=str(item.get("path", "")),
                    language=item.get("language") or None,
                    kind=str(item.get("kind", "code")),
                    symbol_name=item.get("symbol_name") or None,
                    start_line=int(item.get("start_line", 1)),
                    end_line=int(item.get("end_line", 1)),
                    snippet=_make_snippet(str(item.get("text", ""))),
                    score=round(score, 4),
                    vector_rank=None,
                    bm25_rank=rank,
                )
            )
        return results, confidence

    # Hybrid Mode: Reciprocal Rank Fusion (RRF)
    chunk_map: dict[str, dict[str, Any]] = {}
    rrf_scores: dict[str, float] = {}
    v_ranks: dict[str, int] = {}
    b_ranks: dict[str, int] = {}

    for rank, item in enumerate(vector_ranked, start=1):
        cid = str(item.get("chunk_id", ""))
        chunk_map[cid] = item
        v_ranks[cid] = rank
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))

    for rank, item in enumerate(bm25_ranked, start=1):
        cid = str(item.get("chunk_id", ""))
        chunk_map[cid] = item
        b_ranks[cid] = rank
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))

    if not rrf_scores:
        return [], 0.0

    sorted_chunks = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

    if top_vector_sim > 0 and top_bm25_norm > 0:
        confidence = round(0.6 * top_vector_sim + 0.4 * top_bm25_norm, 3)
    elif top_vector_sim > 0:
        confidence = round(top_vector_sim, 3)
    else:
        confidence = round(top_bm25_norm, 3)

    results = []
    for cid in sorted_chunks[:top_k]:
        item = chunk_map[cid]
        results.append(
            SearchResultItem(
                chunk_id=cid,
                path=str(item.get("path", "")),
                language=item.get("language") or None,
                kind=str(item.get("kind", "code")),
                symbol_name=item.get("symbol_name") or None,
                start_line=int(item.get("start_line", 1)),
                end_line=int(item.get("end_line", 1)),
                snippet=_make_snippet(str(item.get("text", ""))),
                score=round(rrf_scores[cid], 5),
                vector_rank=v_ranks.get(cid),
                bm25_rank=b_ranks.get(cid),
            )
        )

    return results, confidence


# ── Step 4A Document Retrieval ──────────────────────────────────────────


def _matches_doc_filters(item: dict[str, Any], filters: Optional[dict[str, Any]]) -> bool:
    """Filter document chunk metadata by page range, kind, or section."""
    if not filters:
        return True
    for key, val in filters.items():
        if val is None:
            continue
        if key == "page_num":
            p_start = int(item.get("page_start", 1))
            p_end = int(item.get("page_end", 1))
            if not (p_start <= int(val) <= p_end):
                return False
        elif key == "page_start":
            if int(item.get("page_start", 1)) < int(val):
                return False
        elif key == "page_end":
            if int(item.get("page_end", 1)) > int(val):
                return False
        elif key == "kind":
            if str(item.get("kind", "")) != str(val):
                return False
        elif key == "section":
            if str(val).lower() not in str(item.get("section", "")).lower():
                return False
        elif item.get(key) != val:
            return False
    return True


def retrieve_document(
    doc_id: str,
    query: str,
    mode: str = "hybrid",
    top_k: int = 6,
    filters: Optional[dict[str, Any]] = None,
    sha256: Optional[str] = None,
    embedder_fn: Optional[Callable[[str], list[float]]] = None,
) -> tuple[list[DocumentSearchResultItem], float]:
    """Retrieve relevant chunks from an indexed PDF document.

    Args:
        doc_id: The document UUID.
        query: User search query.
        mode: "hybrid" | "vector" | "bm25".
        top_k: Number of final results.
        filters: Optional filters (page_num, page_start, page_end, kind, section).
        sha256: Optional document SHA-256 for ChromaDB lookup.
        embedder_fn: Optional embedding function.

    Returns:
        tuple of (list of DocumentSearchResultItem, confidence score).
    """
    settings = get_settings()
    top_k_each = settings.retrieval_top_k_each
    rrf_k = settings.rrf_k
    source_key = f"doc:{doc_id}"

    vector_ranked: list[dict[str, Any]] = []
    vector_distances: list[float] = []
    bm25_ranked: list[dict[str, Any]] = []
    bm25_scores: list[float] = []

    # 1. Vector Search
    if mode in ("vector", "hybrid"):
        q_embedding: Optional[list[float]] = None
        try:
            if embedder_fn is None:
                from app.rag.embedder import embed_query

                embedder_fn = embed_query
            q_embedding = embedder_fn(query)
        except Exception as e:
            logger.warning("Document vector query embedding failed: %s", e)

        if q_embedding:
            # Try ChromaDB if sha256 is provided
            if sha256:
                try:
                    from app.rag.doc_indexer import sanitize_doc_collection_name

                    client = get_chroma_client()
                    col_name = sanitize_doc_collection_name(doc_id, sha256)
                    collection = client.get_collection(col_name)

                    query_res = collection.query(
                        query_embeddings=[q_embedding],
                        n_results=min(top_k_each * 2, max(collection.count(), 1)),
                        include=["metadatas", "documents", "distances"],
                    )

                    if query_res and query_res["ids"] and query_res["ids"][0]:
                        ids = query_res["ids"][0]
                        docs = (
                            query_res["documents"][0]
                            if query_res["documents"]
                            else [""] * len(ids)
                        )
                        metas = (
                            query_res["metadatas"][0]
                            if query_res["metadatas"]
                            else [{}] * len(ids)
                        )
                        dists = (
                            query_res["distances"][0]
                            if query_res["distances"]
                            else [1.0] * len(ids)
                        )

                        for cid, doc, meta, dist in zip(ids, docs, metas, dists):
                            item = dict(meta)
                            item["text"] = doc
                            if _matches_doc_filters(item, filters):
                                vector_ranked.append(item)
                                vector_distances.append(dist)
                                if len(vector_ranked) >= top_k_each:
                                    break
                except Exception as e:
                    logger.debug("ChromaDB document retrieval skipped/failed: %s", e)

            # In-memory vector cache fallback
            if not vector_ranked:
                cached_vecs = vector_cache.get(
                    source_key, required_model=settings.embedding_model
                )
                if cached_vecs:
                    scored_items = []
                    for item, emb in cached_vecs:
                        if _matches_doc_filters(item, filters):
                            sim = sum(a * b for a, b in zip(q_embedding, emb))
                            dist = max(0.0, 1.0 - sim) * 2.0
                            scored_items.append((sim, dist, item))
                    scored_items.sort(key=lambda x: x[0], reverse=True)
                    for _, dist, item in scored_items[:top_k_each]:
                        vector_ranked.append(item)
                        vector_distances.append(dist)

    # 2. BM25 Search
    if mode in ("bm25", "hybrid"):
        cached = bm25_cache.get(source_key)
        if cached:
            bm25_obj, chunk_metas = cached
            tokenized_query = tokenize_code(query)
            if tokenized_query:
                scores = bm25_obj.get_scores(tokenized_query)
                scored_indices = sorted(
                    range(len(scores)), key=lambda i: scores[i], reverse=True
                )
                for idx in scored_indices:
                    score = float(scores[idx])
                    if score <= 0.0:
                        break
                    item = dict(chunk_metas[idx])
                    if _matches_doc_filters(item, filters):
                        bm25_ranked.append(item)
                        bm25_scores.append(score)
                        if len(bm25_ranked) >= top_k_each:
                            break

    # Confidence calculation
    top_vector_sim = 0.0
    if vector_distances:
        top_dist = max(0.0, min(vector_distances[0], 2.0))
        top_vector_sim = max(0.0, 1.0 - (top_dist / 2.0))

    top_bm25_norm = 0.0
    if bm25_scores:
        top_bm25_norm = min(1.0, bm25_scores[0] / (bm25_scores[0] + 10.0))

    # Vector only
    if mode == "vector":
        confidence = round(top_vector_sim, 3)
        results: list[DocumentSearchResultItem] = []
        for rank, (item, dist) in enumerate(
            zip(vector_ranked[:top_k], vector_distances[:top_k]), start=1
        ):
            sim = max(0.0, 1.0 - (min(dist, 2.0) / 2.0))
            results.append(
                DocumentSearchResultItem(
                    chunk_id=str(item.get("chunk_id", "")),
                    document_id=str(item.get("document_id", doc_id)),
                    filename=str(item.get("filename", "")),
                    page_start=int(item.get("page_start", 1)),
                    page_end=int(item.get("page_end", 1)),
                    section=item.get("section") or None,
                    kind=str(item.get("kind", "text")),
                    text=str(item.get("text", "")),
                    score=round(sim, 4),
                    vector_rank=rank,
                    bm25_rank=None,
                )
            )
        return results, confidence

    # BM25 only
    if mode == "bm25":
        confidence = round(top_bm25_norm, 3)
        results = []
        for rank, (item, score) in enumerate(
            zip(bm25_ranked[:top_k], bm25_scores[:top_k]), start=1
        ):
            results.append(
                DocumentSearchResultItem(
                    chunk_id=str(item.get("chunk_id", "")),
                    document_id=str(item.get("document_id", doc_id)),
                    filename=str(item.get("filename", "")),
                    page_start=int(item.get("page_start", 1)),
                    page_end=int(item.get("page_end", 1)),
                    section=item.get("section") or None,
                    kind=str(item.get("kind", "text")),
                    text=str(item.get("text", "")),
                    score=round(score, 4),
                    vector_rank=None,
                    bm25_rank=rank,
                )
            )
        return results, confidence

    # Hybrid RRF
    chunk_map: dict[str, dict[str, Any]] = {}
    rrf_scores: dict[str, float] = {}
    v_ranks: dict[str, int] = {}
    b_ranks: dict[str, int] = {}

    for rank, item in enumerate(vector_ranked, start=1):
        cid = str(item.get("chunk_id", ""))
        chunk_map[cid] = item
        v_ranks[cid] = rank
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))

    for rank, item in enumerate(bm25_ranked, start=1):
        cid = str(item.get("chunk_id", ""))
        chunk_map[cid] = item
        b_ranks[cid] = rank
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))

    if not rrf_scores:
        return [], 0.0

    sorted_chunks = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

    if top_vector_sim > 0 and top_bm25_norm > 0:
        confidence = round(0.6 * top_vector_sim + 0.4 * top_bm25_norm, 3)
    elif top_vector_sim > 0:
        confidence = round(top_vector_sim, 3)
    else:
        confidence = round(top_bm25_norm, 3)

    results = []
    for cid in sorted_chunks[:top_k]:
        item = chunk_map[cid]
        results.append(
            DocumentSearchResultItem(
                chunk_id=cid,
                document_id=str(item.get("document_id", doc_id)),
                filename=str(item.get("filename", "")),
                page_start=int(item.get("page_start", 1)),
                page_end=int(item.get("page_end", 1)),
                section=item.get("section") or None,
                kind=str(item.get("kind", "text")),
                text=str(item.get("text", "")),
                score=round(rrf_scores[cid], 5),
                vector_rank=v_ranks.get(cid),
                bm25_rank=b_ranks.get(cid),
            )
        )

    return results, confidence


def retrieve_source(
    source: str,
    query: str,
    mode: str = "hybrid",
    top_k: int = 6,
    filters: Optional[dict[str, Any]] = None,
    embedder_fn: Optional[Callable[[str], list[float]]] = None,
) -> tuple[list[Any], float]:
    """Universal retriever entry point accepting 'doc:<id>' or 'repo:<id>'."""
    if source.startswith("doc:"):
        doc_id = source[4:]
        return retrieve_document(
            doc_id=doc_id,
            query=query,
            mode=mode,
            top_k=top_k,
            filters=filters,
            embedder_fn=embedder_fn,
        )
    elif source.startswith("repo:"):
        repo_id = source[5:]
        return retrieve(
            repo_id=repo_id,
            query=query,
            mode=mode,
            top_k=top_k,
            filters=filters,
            embedder_fn=embedder_fn,
        )
    else:
        return retrieve(
            repo_id=source,
            query=query,
            mode=mode,
            top_k=top_k,
            filters=filters,
            embedder_fn=embedder_fn,
        )
