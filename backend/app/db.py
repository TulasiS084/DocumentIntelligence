"""SQLite engine, session factory, and repository helpers."""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base, Repo

logger = logging.getLogger(__name__)

engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker[Session]] = None


def init_engine(database_url: Optional[str] = None) -> Engine:
    """Create the SQLAlchemy engine and schema.

    Args:
        database_url: Optional override used by tests.

    Returns:
        The configured engine.
    """
    global engine, SessionLocal
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized at %s", url)
    return engine


def get_session() -> Session:
    """Open a new Session. Callers must close it."""
    if SessionLocal is None:
        init_engine()
    assert SessionLocal is not None
    return SessionLocal()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a session."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_repo(session: Session, repo_id: str) -> Optional[Repo]:
    """Fetch a repo row by id."""
    return session.get(Repo, repo_id)


def find_cached_ready(session: Session, url: str, commit_sha: str) -> Optional[Repo]:
    """Return a ready snapshot for the same URL and commit SHA, if any."""
    stmt = (
        select(Repo)
        .where(
            Repo.url == url,
            Repo.commit_sha == commit_sha,
            Repo.status == "ready",
            Repo.tree_json.is_not(None),
        )
        .order_by(Repo.created_at.desc())
    )
    return session.scalars(stmt).first()


def save_repo(session: Session, repo: Repo) -> Repo:
    """Persist pending changes on a repo row."""
    session.add(repo)
    session.commit()
    session.refresh(repo)
    return repo
