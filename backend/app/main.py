"""FastAPI application: health, ingest, status SSE, and file tree."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.config import get_settings
from app.db import (
    delete_document,
    find_document_by_sha256,
    get_document,
    get_document_page,
    get_repo_file,
    get_repo_summary,
    get_session,
    init_engine,
    list_documents,
    list_repo_summaries,
    list_repos,
    save_document,
)
from app.ingest.cloner import InvalidUrlError, validate_github_url
from app.ingest.documents.pipeline import run_document_pipeline
from app.ingest.documents.validator import DocumentValidationError, stream_and_validate_upload
from app.ingest.pipeline import run_pipeline
from app.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    Document,
    DocumentDetailResponse,
    DocumentListItemResponse,
    DocumentPageResponse,
    DocumentSearchRequest,
    DocumentSearchResponse,
    DocumentUploadItemResponse,
    HealthResponse,
    Repo,
    RepoListItemResponse,
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


@app.get("/api/repos", response_model=list[RepoListItemResponse])
def get_repos() -> list[RepoListItemResponse]:
    """List all analyzed GitHub repositories."""
    session = get_session()
    try:
        repos = list_repos(session)
        out = []
        for r in repos:
            # Extract display name (e.g. "owner/repo" from GitHub URL)
            url_parts = r.url.rstrip("/").split("/")
            name = f"{url_parts[-2]}/{url_parts[-1]}" if len(url_parts) >= 2 else r.url
            out.append(
                RepoListItemResponse(
                    id=r.id,
                    url=r.url,
                    name=name,
                    status=r.status,
                    error=r.error,
                    commit_sha=r.commit_sha,
                    created_at=r.created_at,
                )
            )
        return out
    finally:
        session.close()


# ── Step 4A Document Endpoints ───────────────────────────────────────────


@app.post("/api/documents", response_model=list[DocumentUploadItemResponse])
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> list[DocumentUploadItemResponse]:
    """Upload up to MAX_FILES_PER_UPLOAD PDF documents.

    Validates type, size, pages, and integrity.
    One failing file does not reject the good files in the batch.
    """
    settings = get_settings()
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload more than {settings.max_files_per_upload} files at once.",
        )

    results: list[DocumentUploadItemResponse] = []
    session = get_session()

    try:
        for file in files:
            sanitized_name = file.filename or "document.pdf"
            try:
                (
                    clean_name,
                    stored_name,
                    size_bytes,
                    sha256_hex,
                    page_count,
                ) = await stream_and_validate_upload(
                    upload_file=file,
                    upload_dir=settings.upload_dir,
                    max_bytes=settings.max_upload_bytes,
                    max_pages=settings.max_pdf_pages,
                )

                # Check for cached duplicate by SHA-256
                existing_doc = find_document_by_sha256(session, sha256_hex)
                if existing_doc:
                    # Clean up the newly written duplicate file
                    dup_path = Path(settings.upload_dir) / stored_name
                    if dup_path.exists():
                        try:
                            os.remove(dup_path)
                        except OSError:
                            pass

                    results.append(
                        DocumentUploadItemResponse(
                            document_id=existing_doc.id,
                            filename=existing_doc.filename,
                            status=existing_doc.status,
                            duplicate=True,
                            error=None,
                        )
                    )
                    continue

                # Create document record
                new_doc = Document(
                    filename=clean_name,
                    sha256=sha256_hex,
                    size_bytes=size_bytes,
                    page_count=page_count,
                    status="uploading",
                    stored_name=stored_name,
                )
                save_document(session, new_doc)

                # Launch pipeline background task
                background_tasks.add_task(run_document_pipeline, new_doc.id)

                results.append(
                    DocumentUploadItemResponse(
                        document_id=new_doc.id,
                        filename=clean_name,
                        status="uploading",
                        duplicate=False,
                        error=None,
                    )
                )

            except DocumentValidationError as val_err:
                logger.warning("Upload validation failed for %s: %s", sanitized_name, val_err.message)
                results.append(
                    DocumentUploadItemResponse(
                        document_id="",
                        filename=sanitized_name,
                        status="failed",
                        duplicate=False,
                        error=val_err.message,
                    )
                )
            except Exception as exc:
                logger.error("Unexpected error uploading %s: %s", sanitized_name, exc, exc_info=True)
                results.append(
                    DocumentUploadItemResponse(
                        document_id="",
                        filename=sanitized_name,
                        status="failed",
                        duplicate=False,
                        error=str(exc),
                    )
                )

        return results
    finally:
        session.close()


@app.get("/api/documents", response_model=list[DocumentListItemResponse])
def get_documents() -> list[DocumentListItemResponse]:
    """List all uploaded documents."""
    session = get_session()
    try:
        docs = list_documents(session)
        return [
            DocumentListItemResponse(
                id=d.id,
                filename=d.filename,
                size_bytes=d.size_bytes,
                page_count=d.page_count,
                status=d.status,
                error=d.error,
                created_at=d.created_at,
            )
            for d in docs
        ]
    finally:
        session.close()


@app.get("/api/documents/{doc_id}/status")
async def document_status(doc_id: str) -> StreamingResponse:
    """Stream SSE status updates for a document until ready or failed."""
    session = get_session()
    try:
        doc = get_document(session, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Unknown document")
    finally:
        session.close()

    async def event_stream() -> AsyncIterator[str]:
        last: Optional[str] = None
        while True:
            loop_session = get_session()
            try:
                current = get_document(loop_session, doc_id)
                if current is None:
                    payload = {"status": "failed", "error": "Unknown document"}
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


@app.get("/api/documents/{doc_id}", response_model=DocumentDetailResponse)
def get_document_detail(doc_id: str) -> DocumentDetailResponse:
    """Get full document metadata, warnings, outline, and summary."""
    session = get_session()
    try:
        doc = get_document(session, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Unknown document")

        warnings = json.loads(doc.warnings_json) if doc.warnings_json else []
        summary = json.loads(doc.summary_json) if doc.summary_json else None
        outline = json.loads(doc.outline_json) if doc.outline_json else None

        return DocumentDetailResponse(
            id=doc.id,
            filename=doc.filename,
            sha256=doc.sha256,
            size_bytes=doc.size_bytes,
            page_count=doc.page_count,
            status=doc.status,
            error=doc.error,
            warnings=warnings,
            summary=summary,
            outline=outline,
            indexed=doc.indexed,
            created_at=doc.created_at,
        )
    finally:
        session.close()


@app.get("/api/documents/{doc_id}/pages/{page_num}", response_model=DocumentPageResponse)
def get_page(doc_id: str, page_num: int) -> DocumentPageResponse:
    """Fetch text of a specific page (1-based)."""
    session = get_session()
    try:
        doc = get_document(session, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Unknown document")
        if doc.status not in {"ready", "extracting", "chunking", "indexing", "summarizing", "failed"}:
            raise HTTPException(status_code=409, detail="Document pages are not extracted yet")

        page = get_document_page(session, doc_id, page_num)
        if page is None:
            raise HTTPException(
                status_code=404,
                detail=f"Page {page_num} not found (document has {doc.page_count} pages)",
            )

        return DocumentPageResponse(page_number=page.page_number, text=page.text)
    finally:
        session.close()


@app.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: str) -> FileResponse:
    """Serve the original uploaded PDF inline."""
    settings = get_settings()
    session = get_session()
    try:
        doc = get_document(session, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Unknown document")

        file_path = Path(settings.upload_dir) / doc.stored_name
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Stored PDF file not found on disk")

        return FileResponse(
            path=str(file_path),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{doc.filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    finally:
        session.close()


@app.delete("/api/documents/{doc_id}")
def delete_document_endpoint(doc_id: str) -> dict[str, Any]:
    """Delete document file from disk, SQLite records, and search indices."""
    settings = get_settings()
    session = get_session()
    try:
        doc = get_document(session, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Unknown document")

        stored_file = Path(settings.upload_dir) / doc.stored_name
        sha256 = doc.sha256

        # 1. Clear search index (BM25, vector cache, ChromaDB)
        from app.rag.doc_indexer import delete_document_index

        delete_document_index(doc_id, sha256)

        # 2. Delete database records
        delete_document(session, doc_id)

        # 3. Delete file on disk
        if stored_file.exists():
            try:
                os.remove(stored_file)
            except OSError as e:
                logger.warning("Could not remove stored file %s: %s", stored_file, e)

        return {"deleted": True, "id": doc_id}
    finally:
        session.close()


@app.post("/api/documents/{doc_id}/search", response_model=DocumentSearchResponse)
def search_document(doc_id: str, body: DocumentSearchRequest) -> DocumentSearchResponse:
    """Execute hybrid, vector, or BM25 retrieval over a single document's chunks."""
    session = get_session()
    try:
        doc = get_document(session, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Unknown document")
        if doc.status != "ready":
            raise HTTPException(status_code=409, detail="Document is not ready yet")

        from app.rag.retriever import retrieve_document

        results, confidence = retrieve_document(
            doc_id=doc_id,
            query=body.query,
            mode=body.mode,
            top_k=body.k,
            filters=body.filters,
            sha256=doc.sha256,
        )

        return DocumentSearchResponse(
            document_id=doc_id,
            query=body.query,
            mode=body.mode,
            confidence=confidence,
            results=results,
        )
    finally:
        session.close()
