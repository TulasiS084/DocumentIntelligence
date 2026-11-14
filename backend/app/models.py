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


# ── Step 4A Document Models ─────────────────────────────────────────────


class Document(Base):
    """Persisted metadata and status for an uploaded PDF document."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploading")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stored_name: Mapped[str] = mapped_column(String(128), nullable=False)
    summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outline_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class DocumentPage(Base):
    """A single extracted page from a PDF document."""

    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DocumentChunk(Base):
    """A semantic chunk extracted from a PDF document."""

    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_id"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="text")  # "text" | "table"
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embed_text: Mapped[str] = mapped_column(Text, nullable=False)


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


# ── Step 4A Document API Schemas ─────────────────────────────────────────

DocumentPipelineStatus = Literal[
    "uploading", "extracting", "chunking", "indexing", "summarizing", "ready", "failed"
]


class DocumentStatusEvent(BaseModel):
    """Payload streamed over SSE for document processing."""

    status: DocumentPipelineStatus
    error: Optional[str] = None


class DocumentUploadItemResponse(BaseModel):
    """Result of uploading a single document in a batch."""

    document_id: str
    filename: str
    status: str
    duplicate: bool = False
    error: Optional[str] = None


class DocumentListItemResponse(BaseModel):
    """Compact summary of a document for lists."""

    id: str
    filename: str
    size_bytes: int
    page_count: int
    status: str
    error: Optional[str] = None
    created_at: datetime


class DocumentDetailResponse(BaseModel):
    """Full detail view of an analyzed document."""

    id: str
    filename: str
    sha256: str
    size_bytes: int
    page_count: int
    status: str
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    summary: Optional[dict[str, Any]] = None
    outline: Optional[list[dict[str, Any]]] = None
    indexed: bool = False
    created_at: datetime


class DocumentPageResponse(BaseModel):
    """A single extracted page's text."""

    page_number: int
    text: str


class DocumentSearchRequest(BaseModel):
    """Query parameters for document search."""

    query: str = Field(..., min_length=1, max_length=1000)
    mode: Literal["hybrid", "vector", "bm25"] = "hybrid"
    k: int = Field(6, ge=1, le=50)
    filters: Optional[dict[str, Any]] = None


class DocumentSearchResultItem(BaseModel):
    """A matched document chunk result."""

    chunk_id: str
    document_id: str
    filename: str
    page_start: int
    page_end: int
    section: Optional[str] = None
    kind: str
    text: str
    score: float
    vector_rank: Optional[int] = None
    bm25_rank: Optional[int] = None


class DocumentSearchResponse(BaseModel):
    """Document search results payload."""

    document_id: str
    query: str
    mode: str
    confidence: float
    results: list[DocumentSearchResultItem]


class RepoListItemResponse(BaseModel):
    """Summary of an analyzed repository for the sources list."""

    id: str
    url: str
    name: str
    status: str
    error: Optional[str] = None
    commit_sha: Optional[str] = None
    created_at: datetime
