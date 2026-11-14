"""SQLAlchemy models and Pydantic API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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


class AnalyzeRequest(BaseModel):
    """Request body for starting an analysis."""

    url: str = Field(..., max_length=512)


class AnalyzeResponse(BaseModel):
    """Immediate response after queueing an analysis."""

    repo_id: str
    status: str


PipelineStatus = Literal["cloning", "scanning", "parsing", "graphing", "ready", "failed"]


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
