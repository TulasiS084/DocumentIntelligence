"""SQLite engine, session factory, and repository helpers."""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base, Repo, RepoChunk, RepoFile, RepoSummary

logger = logging.getLogger(__name__)

engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker[Session]] = None


def _migrate_schema(eng: Engine) -> None:
    """Add missing columns to existing tables for backwards compatibility."""
    from sqlalchemy import text
    try:
        with eng.begin() as conn:
            res = conn.execute(text("PRAGMA table_info(repos)"))
            columns = {row[1] for row in res.fetchall()}
            if columns and "graph_json" not in columns:
                conn.execute(text("ALTER TABLE repos ADD COLUMN graph_json TEXT"))
                logger.info("Migrated repos table: added graph_json column")
            if columns and "parse_json" not in columns:
                conn.execute(text("ALTER TABLE repos ADD COLUMN parse_json TEXT"))
                logger.info("Migrated repos table: added parse_json column")
            if columns and "indexed" not in columns:
                conn.execute(text("ALTER TABLE repos ADD COLUMN indexed BOOLEAN DEFAULT 0"))
                logger.info("Migrated repos table: added indexed column")
            if columns and "embedding_model" not in columns:
                conn.execute(text("ALTER TABLE repos ADD COLUMN embedding_model TEXT"))
                logger.info("Migrated repos table: added embedding_model column")
    except Exception:
        logger.debug("Schema migration skipped or table does not exist yet", exc_info=True)


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
    _migrate_schema(engine)
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
    """Return a ready and indexed snapshot for the same URL, commit SHA, and embedding model."""
    current_model = get_settings().embedding_model
    stmt = (
        select(Repo)
        .where(
            Repo.url == url,
            Repo.commit_sha == commit_sha,
            Repo.status == "ready",
            Repo.tree_json.is_not(None),
            Repo.graph_json.is_not(None),
            Repo.indexed.is_(True),
            (Repo.embedding_model == current_model) | (Repo.embedding_model.is_(None)),
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


def get_repo_file(session: Session, repo_id: str, path: str) -> Optional[RepoFile]:
    """Fetch a single stored file by repo and POSIX path."""
    stmt = select(RepoFile).where(RepoFile.repo_id == repo_id, RepoFile.path == path)
    return session.scalars(stmt).first()


def save_repo_chunks(session: Session, chunks: list[RepoChunk]) -> None:
    """Bulk save repo chunks."""
    if not chunks:
        return
    session.add_all(chunks)
    session.commit()


def get_repo_chunks(
    session: Session,
    repo_id: str,
    path: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[RepoChunk]:
    """Fetch stored chunks for a repository."""
    stmt = select(RepoChunk).where(RepoChunk.repo_id == repo_id)
    if path:
        stmt = stmt.where(RepoChunk.path == path)
    stmt = stmt.order_by(RepoChunk.path, RepoChunk.start_line)
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def save_repo_summary(session: Session, summary: RepoSummary) -> RepoSummary:
    """Persist or update a repo summary."""
    existing = get_repo_summary(session, summary.repo_id, summary.level, summary.path)
    if existing:
        existing.text = summary.text
        existing.source = summary.source
        session.commit()
        session.refresh(existing)
        return existing
    session.add(summary)
    session.commit()
    session.refresh(summary)
    return summary


def get_repo_summary(
    session: Session, repo_id: str, level: str, path: Optional[str] = ""
) -> Optional[RepoSummary]:
    """Fetch a specific repo summary."""
    normalized_path = path or ""
    stmt = select(RepoSummary).where(
        RepoSummary.repo_id == repo_id,
        RepoSummary.level == level,
        RepoSummary.path == normalized_path,
    )
    return session.scalars(stmt).first()


def list_repo_summaries(
    session: Session, repo_id: str, level: Optional[str] = None
) -> list[RepoSummary]:
    """Fetch all summaries for a repository, optionally filtered by level."""
    stmt = select(RepoSummary).where(RepoSummary.repo_id == repo_id)
    if level:
        stmt = stmt.where(RepoSummary.level == level)
    return list(session.scalars(stmt).all())
