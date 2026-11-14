"""ChromaDB vector store and BM25 indexing for code repositories."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional
from collections import OrderedDict

from app.config import get_settings
from app.models import RepoChunk

logger = logging.getLogger(__name__)

# Code-aware tokenization regexes
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_SPLIT_CHARS_RE = re.compile(r"[^a-zA-Z0-9_]+")


def tokenize_code(text: str) -> list[str]:
    """Tokenize code text into subwords and original tokens for BM25.

    Splits on symbols, underscores, and camelCase transitions, while preserving
    the original full token so exact identifier matches are boosted.
    """
    if not text:
        return []

    tokens: list[str] = []
    # Split by non-alphanumeric (excluding underscore)
    raw_words = _SPLIT_CHARS_RE.split(text)

    for word in raw_words:
        if not word:
            continue
        lower_word = word.lower()
        tokens.append(lower_word)

        # Split snake_case
        parts = word.split("_")
        if len(parts) > 1:
            for part in parts:
                if part:
                    tokens.append(part.lower())

        # Split camelCase / PascalCase
        for part in parts:
            if not part:
                continue
            split_camel = _CAMEL_RE.sub(r"\1 \2", part).split()
            if len(split_camel) > 1:
                for sub in split_camel:
                    if sub:
                        tokens.append(sub.lower())

    return tokens


# In-memory BM25 cache with simple LRU eviction
class BM25Cache:
    """Thread-safe-ish LRU cache for BM25 indexes."""

    def __init__(self, capacity: int = 16) -> None:
        self.capacity = capacity
        self._cache: OrderedDict[str, tuple[Any, list[dict[str, Any]]]] = OrderedDict()

    def get(self, repo_id: str) -> Optional[tuple[Any, list[dict[str, Any]]]]:
        if repo_id in self._cache:
            self._cache.move_to_end(repo_id)
            return self._cache[repo_id]
        return None

    def put(self, repo_id: str, bm25: Any, chunk_meta: list[dict[str, Any]]) -> None:
        if repo_id in self._cache:
            self._cache.move_to_end(repo_id)
        self._cache[repo_id] = (bm25, chunk_meta)
        if len(self._cache) > self.capacity:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()


bm25_cache = BM25Cache(capacity=16)


class VectorCache:
    """In-memory vector cache for embeddings with model version tracking."""

    def __init__(self, capacity: int = 16) -> None:
        self.capacity = capacity
        # repo_id -> (items, embedding_model)
        self._cache: OrderedDict[str, tuple[list[tuple[dict[str, Any], list[float]]], str]] = OrderedDict()

    def get(
        self, repo_id: str, required_model: Optional[str] = None
    ) -> Optional[list[tuple[dict[str, Any], list[float]]]]:
        if repo_id in self._cache:
            items, model_name = self._cache[repo_id]
            if required_model and model_name and model_name != required_model:
                logger.info(
                    "Cached vectors for %s used different model (%s != %s); invalidating",
                    repo_id,
                    model_name,
                    required_model,
                )
                del self._cache[repo_id]
                return None
            self._cache.move_to_end(repo_id)
            return items
        return None

    def put(
        self,
        repo_id: str,
        items: list[tuple[dict[str, Any], list[float]]],
        embedding_model: str = "",
    ) -> None:
        if repo_id in self._cache:
            self._cache.move_to_end(repo_id)
        self._cache[repo_id] = (items, embedding_model)
        if len(self._cache) > self.capacity:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()


vector_cache = VectorCache(capacity=16)


def sanitize_collection_name(repo_id: str, commit_sha: Optional[str] = None) -> str:
    """Create a Chroma-compliant collection name (3-63 alphanumeric/dash/underscore chars)."""
    sha_part = (commit_sha or "head")[:8]
    clean_repo = re.sub(r"[^a-zA-Z0-9_-]", "", repo_id)[:24]
    clean_sha = re.sub(r"[^a-zA-Z0-9_-]", "", sha_part)
    name = f"repo_{clean_repo}_{clean_sha}"
    # Chroma requires length 3-63, starting and ending with alphanumeric
    if len(name) < 3:
        name = f"col_{name}"
    if len(name) > 63:
        name = name[:63]
    if not name[0].isalnum():
        name = "c" + name[1:]
    if not name[-1].isalnum():
        name = name[:-1] + "0"
    return name


def get_chroma_client():
    """Get persistent ChromaDB client."""
    import chromadb
    settings = get_settings()
    return chromadb.PersistentClient(path=settings.chroma_path)


def index_chunks(
    repo_id: str,
    chunks: list[RepoChunk],
    commit_sha: Optional[str] = None,
    embedder_fn: Optional[Callable[[list[str]], list[list[float]]]] = None,
) -> None:
    """Index chunks in ChromaDB vector store and build in-memory BM25 index.

    Args:
        repo_id: ID of the repository.
        chunks: List of RepoChunk models to index.
        commit_sha: Optional commit SHA for collection naming.
        embedder_fn: Optional embedding callable, defaults to embedder.embed_texts.
    """
    if not chunks:
        logger.info("No chunks to index for repo %s", repo_id)
        return

    # 1. Build and cache BM25 Index
    try:
        from rank_bm25 import BM25Plus

        tokenized_corpus = [tokenize_code(chunk.embed_text) for chunk in chunks]
        bm25_index = BM25Plus(tokenized_corpus)
        chunk_metas = [
            {
                "chunk_id": chunk.chunk_id,
                "path": chunk.path,
                "language": chunk.language or "",
                "kind": chunk.kind,
                "symbol_name": chunk.symbol_name or "",
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "text": chunk.text,
            }
            for chunk in chunks
        ]
        bm25_cache.put(repo_id, bm25_index, chunk_metas)
        logger.info("BM25 index built for repo %s with %d chunks", repo_id, len(chunks))
    except Exception as e:
        logger.error("Failed to build BM25 index for repo %s: %s", repo_id, e, exc_info=True)

    # 2. Embedding generation & Vector caching
    chunk_metas = [
        {
            "chunk_id": chunk.chunk_id,
            "path": chunk.path,
            "language": chunk.language or "",
            "kind": chunk.kind,
            "symbol_name": chunk.symbol_name or "",
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
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
        vector_cache.put(repo_id, list(zip(chunk_metas, all_embeddings)), embedding_model=settings.embedding_model)
    except Exception as e:
        logger.warning("Embedding generation encountered issue for repo %s: %s", repo_id, e)

    # 3. ChromaDB Indexing
    try:
        client = get_chroma_client()
        col_name = sanitize_collection_name(repo_id, commit_sha)

        try:
            client.delete_collection(col_name)
        except Exception:
            pass

        collection = client.create_collection(
            name=col_name,
            metadata={
                "repo_id": repo_id,
                "commit_sha": commit_sha or "",
                "embedding_model": settings.embedding_model,
            },
        )

        batch_size = 64
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            batch_embs = all_embeddings[i : i + batch_size] if all_embeddings else embedder_fn([c.embed_text for c in batch])
            ids = [f"{repo_id}_{c.chunk_id}_{i+idx}" for idx, c in enumerate(batch)]
            metadatas = [
                {
                    "repo_id": repo_id,
                    "chunk_id": c.chunk_id,
                    "path": c.path,
                    "language": c.language or "",
                    "kind": c.kind,
                    "symbol_name": c.symbol_name or "",
                    "start_line": c.start_line,
                    "end_line": c.end_line,
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
            "ChromaDB collection '%s' created with %d chunks for repo %s",
            col_name,
            len(chunks),
            repo_id,
        )
    except Exception as e:
        logger.info("ChromaDB vector indexing skipped or unavailable (%s); using in-memory vector cache", e)
