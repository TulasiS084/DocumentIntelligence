"""Shared fixtures for backend tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import init_engine


@pytest.fixture
def temp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point database and clone temp dir at a pytest tmp path."""
    db_path = tmp_path / "test.db"
    chroma_dir = tmp_path / "chroma_data"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("TEMP_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_PATH", str(chroma_dir))
    get_settings.cache_clear()
    init_engine(f"sqlite:///{db_path.as_posix()}")
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def mock_rag_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock external embedding and LLM calls so tests run fast without network."""
    import math

    def _fake_embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
        # Fast deterministic code-tokenized hashed vector for testing
        from app.rag.indexer import tokenize_code

        vecs = []
        for t in texts:
            vec = [0.0] * 384
            words = tokenize_code(t)
            for w in words:
                idx = abs(hash(w)) % 384
                vec[idx] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vecs.append([x / norm for x in vec])
        return vecs

    def _fake_embed_query(query: str) -> list[float]:
        return _fake_embed_texts([query])[0]

    def _fake_generate(prompt: str, **kwargs) -> str:
        if "exact keys" in prompt or "overview" in prompt:
            return (
                '{\n'
                '  "overview": "A portfolio project analyzer.",\n'
                '  "stack": ["Python", "TypeScript"],\n'
                '  "how_to_run": "pytest backend/tests",\n'
                '  "folder_guide": {"backend": "API server"},\n'
                '  "key_files": ["backend/app/main.py"]\n'
                '}'
            )
        return "Deterministic summary of the source code file."

    from app.rag import embedder
    from app import llm

    monkeypatch.setattr(embedder, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(embedder, "embed_query", _fake_embed_query)
    monkeypatch.setattr(llm, "generate", _fake_generate)


@pytest.fixture
def client(temp_settings: Path) -> Generator[TestClient, None, None]:
    """HTTP client with an isolated SQLite database."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
