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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("TEMP_DIR", str(tmp_path))
    get_settings.cache_clear()
    init_engine(f"sqlite:///{db_path.as_posix()}")
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def client(temp_settings: Path) -> Generator[TestClient, None, None]:
    """HTTP client with an isolated SQLite database."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
