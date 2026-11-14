"""Sentence-Transformers lazy CPU embedder.

All vector embedding calls throughout the application MUST go through this module.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

_MODEL: Optional[object] = None


def get_embedding_model() -> object:
    """Return the cached SentenceTransformer instance, loading it on first use."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    settings = get_settings()
    model_name = settings.embedding_model
    logger.info("Loading embedding model %s on CPU...", model_name)

    import os
    import torch
    from sentence_transformers import SentenceTransformer

    # Optimal thread count for CPU inference on laptops/desktops
    optimal_threads = min(4, os.cpu_count() or 4)
    torch.set_num_threads(optimal_threads)

    _MODEL = SentenceTransformer(model_name, device="cpu")
    logger.info("Embedding model %s loaded successfully with %d CPU threads", model_name, optimal_threads)
    return _MODEL


def embed_texts(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Generate normalized embedding vectors for a list of texts in batches.

    Parameters
    ----------
    texts:
        List of string documents or chunks to embed.
    batch_size:
        Number of items per inference batch.

    Returns
    -------
    List of unit-normalized float vectors.
    """
    if not texts:
        return []

    import torch

    model: any = get_embedding_model()
    with torch.inference_mode():
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
    return [vec.tolist() for vec in embeddings]


def embed_query(query: str) -> list[float]:
    """Generate normalized embedding vector for a single query string.

    Parameters
    ----------
    query:
        The search query text.

    Returns
    -------
    A single unit-normalized float vector.
    """
    results = embed_texts([query])
    if not results:
        return []
    return results[0]
