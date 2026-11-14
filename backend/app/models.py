"""SQLAlchemy models and Pydantic API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for ORM models."""


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Repo(Base):
    """Persisted analysis snapshot for a GitHub repository."""

    __tablename__ = "repos"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    url: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="cloning")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tree_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stats_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    graph_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RepoFile(Base):
    """A single file stored during repository analysis."""

    __tablename__ = "repo_files"
    __table_args__ = (UniqueConstraint("repo_id", "path"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repos.id"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    loc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RepoChunk(Base):
    """A granular semantic code or documentation chunk."""

    __tablename__ = "repo_chunks"
    __table_args__ = (UniqueConstraint("repo_id", "chunk_id"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repos.id"), nullable=False, index=True
    )
    chunk_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embed_text: Mapped[str] = mapped_column(Text, nullable=False)


class RepoSummary(Base):
    """Layered repository summary (file, folder, or project level)."""

    __tablename__ = "repo_summaries"
    __table_args__ = (UniqueConstraint("repo_id", "level", "path"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repos.id"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(32), nullable=False)  # "file", "folder", "project"
    path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="llm")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AnalyzeRequest(BaseModel):
    """Request body for starting an analysis."""

    url: str = Field(..., max_length=512)


class AnalyzeResponse(BaseModel):
    """Immediate response after queueing an analysis."""

    repo_id: str
    status: str


PipelineStatus = Literal[
    "cloning", "scanning", "parsing", "graphing", "indexing", "summarizing", "ready", "failed"
]


class StatusEvent(BaseModel):
    """Payload streamed over SSE."""

    status: PipelineStatus
    error: Optional[str] = None


class TreeResponse(BaseModel):
    """File tree plus aggregate stats."""

    tree: dict[str, Any]
    stats: dict[str, Any]


class HealthResponse(BaseModel):
    """Liveness payload."""

    status: Literal["ok"]


class SearchRequest(BaseModel):
    """Query parameters for hybrid search."""

    query: str = Field(..., min_length=1, max_length=1000)
    mode: Literal["hybrid", "vector", "bm25"] = "hybrid"
    top_k: int = Field(6, ge=1, le=50)
    filters: Optional[dict[str, Any]] = None


class SearchResultItem(BaseModel):
    """A matched chunk result."""

    chunk_id: str
    path: str
    language: Optional[str] = None
    kind: str
    symbol_name: Optional[str] = None
    start_line: int
    end_line: int
    snippet: str
    score: float
    vector_rank: Optional[int] = None
    bm25_rank: Optional[int] = None


class SearchResponse(BaseModel):
    """Search results response payload."""

    repo_id: str
    query: str
    mode: str
    confidence: float
    results: list[SearchResultItem]


class SummaryResponse(BaseModel):
    """Project-level summary response."""

    repo_id: str
    overview: Optional[str] = None
    stack: Optional[list[str]] = None
    how_to_run: Optional[str] = None
    folder_guide: Optional[dict[str, str]] = None
    key_files: Optional[list[str]] = None
    source: str = "llm"
