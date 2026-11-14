"""FastAPI application: health, ingest, status SSE, and file tree."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import get_settings
from app.db import get_repo_file, get_repo_summary, get_session, init_engine, list_repo_summaries
from app.ingest.cloner import InvalidUrlError, validate_github_url
from app.ingest.pipeline import run_pipeline
from app.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    HealthResponse,
    Repo,
    SearchRequest,
    SearchResponse,
    SummaryResponse,
)

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

    # Log LLM configuration and key status safely without exposing keys
    if settings.llm_provider == "gemini":
        key_configured = "yes" if settings.is_gemini_key_configured else "no"
        model_name = settings.gemini_model
    elif settings.llm_provider == "groq":
        key_configured = "yes" if settings.is_groq_key_configured else "no"
        model_name = settings.groq_model
    else:
        key_configured = "n/a (local)"
        model_name = settings.ollama_model

    logger.info("LLM provider: %s, model: %s, key configured: %s", settings.llm_provider, model_name, key_configured)

    # Log active vector store
    try:
        import chromadb
        active_vs = f"ChromaDB (version {getattr(chromadb, '__version__', 'unknown')})"
    except ImportError:
        active_vs = "Built-in fallback (normalized vector store)"
    logger.info("Active vector store: %s", active_vs)

    # Pre-warm embedder in a daemon thread so analysis doesn't wait on cold-start
    import threading

    def _warmup_embedder() -> None:
        try:
            from app.rag.embedder import embed_query
            embed_query("warmup")
            logger.info("Embedding model pre-warmed and ready in memory")
        except Exception as e:
            logger.debug("Embedder warmup skipped: %s", e)

    threading.Thread(target=_warmup_embedder, daemon=True).start()

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


def _attach_summaries_to_tree(node: dict, summary_map: dict[str, str]) -> None:
    """Recursively attach file summaries to file tree nodes."""
    if node.get("type") == "file":
        p = node.get("path")
        if p and p in summary_map:
            node["summary"] = summary_map[p]
    for child in node.get("children") or []:
        _attach_summaries_to_tree(child, summary_map)


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
        tree = json.loads(repo.tree_json)
        summaries = list_repo_summaries(session, repo_id, level="file")
        if summaries:
            s_map = {s.path: s.text for s in summaries if s.path}
            _attach_summaries_to_tree(tree, s_map)
        return {
            "tree": tree,
            "stats": json.loads(repo.stats_json or "{}"),
        }
    finally:
        session.close()


@app.get("/api/repos/{repo_id}/graph/overview")
def repo_graph_overview(repo_id: str, include_hidden: bool = False) -> dict:
    """Return simplified folder-level graph with merged edges and counts."""
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
        if repo.status != "ready" or not repo.graph_json:
            raise HTTPException(status_code=409, detail="Repository is not ready yet")
        graph_data = json.loads(repo.graph_json)
        folder_graph = graph_data.get("folder_graph", {})
        folder_nodes = folder_graph.get("nodes", [])
        folder_edges = folder_graph.get("edges", [])

        if not include_hidden:
            hidden_names = {"tests", "__tests__", "test", "docs", "doc", ".github", "config"}
            visible_nodes = []
            for fn in folder_nodes:
                name_lower = fn.get("label", "").lower()
                role = fn.get("role", "")
                if role in ("test", "doc", "config") or name_lower in hidden_names:
                    continue
                visible_nodes.append(fn)

            visible_ids = {fn["id"] for fn in visible_nodes}
            visible_edges = [
                fe for fe in folder_edges
                if fe.get("source") in visible_ids and fe.get("target") in visible_ids
            ]
            folder_nodes = visible_nodes
            folder_edges = visible_edges

        entry_points = graph_data.get("entry_points", [])

        return {
            "nodes": folder_nodes,
            "edges": folder_edges,
            "entry_points": entry_points,
            "reading_order": graph_data.get("reading_order", []),
        }
    finally:
        session.close()


@app.get("/api/repos/{repo_id}/graph")
def repo_graph_filtered(
    repo_id: str,
    folder: Optional[str] = None,
    kinds: str = "import",
) -> dict:
    """Return file-level nodes and edges filtered by folder and edge kinds."""
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
        if repo.status != "ready" or not repo.graph_json:
            raise HTTPException(status_code=409, detail="Repository is not ready yet")
        graph_data = json.loads(repo.graph_json)
        all_nodes = graph_data.get("nodes", [])
        all_edges = graph_data.get("edges", [])

        if folder is not None:
            target_folder = folder.strip()
            filtered_nodes = [n for n in all_nodes if n.get("folder") == target_folder]
        else:
            filtered_nodes = all_nodes

        node_ids = {n["id"] for n in filtered_nodes}
        allowed_kinds = {k.strip() for k in kinds.split(",") if k.strip()}

        filtered_edges = [
            e for e in all_edges
            if e.get("kind") in allowed_kinds
            and (e.get("source") in node_ids or e.get("target") in node_ids)
        ]

        return {
            "nodes": filtered_nodes,
            "edges": filtered_edges,
            "entry_points": graph_data.get("entry_points", []),
        }
    finally:
        session.close()


@app.get("/api/repos/{repo_id}/graph/node")
def repo_graph_node(repo_id: str, id: str) -> dict:
    """Return details for a single node: dependencies, dependents, symbols, summary."""
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
        if repo.status != "ready" or not repo.graph_json:
            raise HTTPException(status_code=409, detail="Repository is not ready yet")
        graph_data = json.loads(repo.graph_json)
        nodes = graph_data.get("nodes", [])
        target_node = next((n for n in nodes if n.get("id") == id), None)
        if target_node is None:
            raise HTTPException(status_code=404, detail="Node not found in graph")

        edges = graph_data.get("edges", [])
        dependencies = sorted({e["target"] for e in edges if e.get("source") == id})
        dependents = sorted({e["source"] for e in edges if e.get("target") == id})

        rev_adj: dict[str, list[str]] = {}
        for e in edges:
            rev_adj.setdefault(e.get("target", ""), []).append(e.get("source", ""))

        visited: set[str] = set()
        queue = [id]
        while queue:
            curr = queue.pop(0)
            for parent in rev_adj.get(curr, []):
                if parent not in visited and parent != id:
                    visited.add(parent)
                    queue.append(parent)
        transitive_count = len(visited)

        symbols: list[dict] = []
        if repo.parse_json:
            parsed_list = json.loads(repo.parse_json)
            target_pf = next((p for p in parsed_list if p.get("path") == id), None)
            if target_pf and "symbols" in target_pf:
                symbols = target_pf["symbols"]

        return {
            "id": target_node["id"],
            "label": target_node.get("label", target_node["id"]),
            "path": target_node["id"],
            "folder": target_node.get("folder", "."),
            "role": target_node.get("role", "other"),
            "kind": target_node.get("kind", "code"),
            "language": target_node.get("language"),
            "loc": target_node.get("loc", 0),
            "summary": target_node.get("summary", ""),
            "external": target_node.get("external", []),
            "dependencies": dependencies,
            "dependents": dependents,
            "symbols": symbols,
            "transitive_dependents_count": transitive_count,
        }
    finally:
        session.close()


@app.get("/api/repos/{repo_id}/reading-order")
def repo_reading_order(repo_id: str) -> dict:
    """Return deterministic reading order for key repository files."""
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
        if repo.status != "ready" or not repo.graph_json:
            raise HTTPException(status_code=409, detail="Repository is not ready yet")
        graph_data = json.loads(repo.graph_json)
        return {
            "reading_order": graph_data.get("reading_order", []),
        }
    finally:
        session.close()


@app.get("/api/repos/{repo_id}/file")
def repo_file_content(repo_id: str, path: str) -> dict:
    """Return stored content and metadata for a specific repository file."""
    if not path or ".." in path or path.startswith("/") or path.startswith("\\") or ":" in path:
        raise HTTPException(status_code=400, detail="Invalid file path")

    clean_path = path.replace("\\", "/").lstrip("/")

    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
        if repo.status != "ready":
            raise HTTPException(status_code=409, detail="Repository is not ready yet")

        repo_file = get_repo_file(session, repo_id, clean_path)
        if repo_file is None:
            raise HTTPException(status_code=404, detail="File not found")

        return {
            "path": repo_file.path,
            "language": repo_file.language,
            "loc": repo_file.loc,
            "content": repo_file.content or "",
        }
    finally:
        session.close()


@app.get("/api/repos/{repo_id}/summary")
def repo_summary(repo_id: str, level: str = "project", path: Optional[str] = None) -> dict:
    """Return layered repository summary (project, folder, or file level)."""
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
        if repo.status != "ready":
            raise HTTPException(status_code=409, detail="Repository is not ready yet")

        if level == "project":
            summary = get_repo_summary(session, repo_id, "project", "")
            if summary:
                try:
                    data = json.loads(summary.text)
                    if isinstance(data, dict):
                        data["repo_id"] = repo_id
                        data["source"] = summary.source
                        return data
                except Exception:
                    pass
            return {
                "repo_id": repo_id,
                "overview": "Analysis ready.",
                "stack": [],
                "how_to_run": "See README.md for instructions.",
                "folder_guide": {},
                "key_files": [],
                "source": "deterministic",
            }

        summary = get_repo_summary(session, repo_id, level, path or "")
        if not summary:
            raise HTTPException(status_code=404, detail=f"Summary for {level} not found")
        return {
            "repo_id": repo_id,
            "level": level,
            "path": summary.path,
            "text": summary.text,
            "source": summary.source,
        }
    finally:
        session.close()


@app.post("/api/repos/{repo_id}/search", response_model=SearchResponse)
def repo_search(repo_id: str, body: SearchRequest) -> SearchResponse:
    """Execute hybrid, vector, or BM25 search over code chunks."""
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Unknown repository")
        if repo.status != "ready":
            raise HTTPException(status_code=409, detail="Repository is not ready yet")

        from app.rag.retriever import retrieve

        results, confidence = retrieve(
            repo_id=repo_id,
            query=body.query,
            mode=body.mode,
            top_k=body.top_k,
            filters=body.filters,
            commit_sha=repo.commit_sha,
        )
        return SearchResponse(
            repo_id=repo_id,
            query=body.query,
            mode=body.mode,
            confidence=confidence,
            results=results,
        )
    finally:
        session.close()
