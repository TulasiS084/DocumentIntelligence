"""FastAPI application: health, ingest, status SSE, and file tree."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import get_settings
from app.db import get_session, init_engine
from app.ingest.cloner import InvalidUrlError, validate_github_url
from app.ingest.pipeline import run_pipeline
from app.models import AnalyzeRequest, AnalyzeResponse, HealthResponse, Repo

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure logging and the database on startup."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    init_engine(settings.database_url)
    logger.info("Repo Analyzer API started")
    yield


app = FastAPI(
    title="Repo Analyzer",
    version="0.1.0",
    description="Step 1: safe clone, scan, and file tree for public GitHub repos.",
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(InvalidUrlError)
async def invalid_url_handler(_request: object, exc: InvalidUrlError) -> JSONResponse:
    """Map invalid GitHub URLs to HTTP 400."""
    return JSONResponse(status_code=400, content={"detail": exc.message, "code": exc.code})


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok")


@app.post("/api/repos", response_model=AnalyzeResponse, status_code=202)
def create_repo(
    body: AnalyzeRequest, background_tasks: BackgroundTasks
) -> AnalyzeResponse:
    """Validate the URL, persist a row, and start the ingest pipeline."""
    canonical = validate_github_url(body.url)
    session = get_session()
    try:
        repo = Repo(url=canonical, status="cloning")
        session.add(repo)
        session.commit()
        session.refresh(repo)
        repo_id = repo.id
        status = repo.status
    finally:
        session.close()
    background_tasks.add_task(run_pipeline, repo_id)
    return AnalyzeResponse(repo_id=repo_id, status=status)


@app.get("/api/repos/{repo_id}/status")
async def repo_status(repo_id: str) -> StreamingResponse:
    """Stream status changes until the pipeline reaches ready or failed."""
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
    finally:
        session.close()

    async def event_stream() -> AsyncIterator[str]:
        last: str | None = None
        while True:
            loop_session = get_session()
            try:
                current = loop_session.get(Repo, repo_id)
                if current is None:
                    payload = {"status": "failed", "error": "Unknown repository"}
                    yield f"event: status\ndata: {json.dumps(payload)}\n\n"
                    return
                payload = {"status": current.status, "error": current.error}
                encoded = json.dumps(payload)
                if encoded != last:
                    yield f"event: status\ndata: {encoded}\n\n"
                    last = encoded
                if current.status in {"ready", "failed"}:
                    return
            finally:
                loop_session.close()
            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/repos/{repo_id}/tree")
def repo_tree(repo_id: str) -> dict:
    """Return the nested file tree and stats once analysis is ready."""
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
        if repo.status != "ready" or not repo.tree_json:
            raise HTTPException(status_code=409, detail="Repository is not ready yet")
        return {
            "tree": json.loads(repo.tree_json),
            "stats": json.loads(repo.stats_json or "{}"),
        }
    finally:
        session.close()
