"""Clone, scan, parse, graph, persist, and always clean up the working tree."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import find_cached_ready, get_session, save_repo, save_repo_chunks
from app.ingest.cloner import CloneError, cleanup, clone_repo
from app.ingest.scanner import scan_repository
from app.models import Repo, RepoChunk, RepoFile, RepoSummary

logger = logging.getLogger(__name__)


def _set_status(session: Session, repo: Repo, status: str, error: str | None = None) -> None:
    """Update and persist pipeline status."""
    repo.status = status
    repo.error = error
    save_repo(session, repo)
    logger.info("Repo %s status -> %s", repo.id, status)


def _collect_files_from_tree(tree: dict, root_path: str) -> list[dict]:
    """Walk the scan tree and read non-skipped file contents from disk."""
    results: list[dict] = []

    def _walk(node: dict) -> None:
        if node.get("type") == "file" and not node.get("skipped", True):
            file_path = os.path.join(root_path, node["path"].replace("/", os.sep))
            try:
                with open(file_path, encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError:
                logger.debug("Could not read %s for file storage", file_path, exc_info=True)
                content = ""
            results.append(
                {
                    "path": node["path"],
                    "language": node.get("language"),
                    "loc": node.get("loc"),
                    "content": content,
                }
            )
        for child in node.get("children") or []:
            _walk(child)

    _walk(tree)
    return results


def _copy_repo_artifacts(session: Session, source_id: str, target_id: str) -> None:
    """Duplicate repo_files, chunks, and summaries from a cached repo into target repo."""
    from sqlalchemy import select

    # Files
    f_stmt = select(RepoFile).where(RepoFile.repo_id == source_id)
    for src in session.scalars(f_stmt).all():
        session.add(
            RepoFile(
                repo_id=target_id,
                path=src.path,
                language=src.language,
                loc=src.loc,
                content=src.content,
            )
        )

    # Chunks
    c_stmt = select(RepoChunk).where(RepoChunk.repo_id == source_id)
    for chunk in session.scalars(c_stmt).all():
        session.add(
            RepoChunk(
                repo_id=target_id,
                chunk_id=chunk.chunk_id,
                path=chunk.path,
                language=chunk.language,
                kind=chunk.kind,
                symbol_name=chunk.symbol_name,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                text=chunk.text,
                embed_text=chunk.embed_text,
            )
        )

    # Summaries
    s_stmt = select(RepoSummary).where(RepoSummary.repo_id == source_id)
    for summ in session.scalars(s_stmt).all():
        session.add(
            RepoSummary(
                repo_id=target_id,
                level=summ.level,
                path=summ.path,
                text=summ.text,
                source=summ.source,
            )
        )

    session.commit()


def run_pipeline(repo_id: str) -> None:
    """Execute clone -> scan -> store files -> parse -> graph -> store.

    Always deletes the temporary clone. Failures set status ``failed``.
    """
    session = get_session()
    clone_path: str | None = None
    try:
        repo = session.get(Repo, repo_id)
        if repo is None:
            logger.error("Pipeline started for unknown repo id %s", repo_id)
            return

        _set_status(session, repo, "cloning")
        result = clone_repo(repo.url)
        clone_path = result.path
        repo.commit_sha = result.commit_sha
        save_repo(session, repo)

        cached = find_cached_ready(session, repo.url, result.commit_sha)
        if cached is not None and cached.id != repo.id:
            logger.info(
                "Cache hit for %s@%s (from %s)", repo.url, result.commit_sha, cached.id
            )
            repo.tree_json = cached.tree_json
            repo.stats_json = cached.stats_json
            repo.graph_json = cached.graph_json
            repo.parse_json = cached.parse_json
            repo.indexed = True
            save_repo(session, repo)
            _copy_repo_artifacts(session, cached.id, repo.id)
            _set_status(session, repo, "ready")
            return

        # ── scan ────────────────────────────────────────────────────
        _set_status(session, repo, "scanning")
        tree, stats = scan_repository(result.path)
        repo.tree_json = json.dumps(tree)
        repo.stats_json = json.dumps(stats)
        save_repo(session, repo)

        # ── store file contents ─────────────────────────────────────
        file_records = _collect_files_from_tree(tree, result.path)
        for rec in file_records:
            session.add(
                RepoFile(
                    repo_id=repo.id,
                    path=rec["path"],
                    language=rec["language"],
                    loc=rec["loc"],
                    content=rec["content"],
                )
            )
        session.commit()

        # ── parse ───────────────────────────────────────────────────
        _set_status(session, repo, "parsing")
        parsed_files = []
        try:
            from app.ingest.parsers.registry import parse_file  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("Parser registry not available; skipping parse & graph")
            from app.ingest.parsers.models import ParsedFile

            for rec in file_records:
                parsed_files.append(
                    ParsedFile(
                        path=rec["path"],
                        language=rec["language"] or "other",
                        kind="other",
                        parse_error="parser not installed",
                    )
                )
        else:
            all_paths = {rec["path"] for rec in file_records}
            for rec in file_records:
                try:
                    pf = parse_file(rec["path"], rec["content"], rec["language"], all_paths=all_paths)
                    parsed_files.append(pf)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Parse failed for %s: %s", rec["path"], exc)
                    from app.ingest.parsers.models import ParsedFile

                    parsed_files.append(
                        ParsedFile(
                            path=rec["path"],
                            language=rec["language"] or "other",
                            kind="other",
                            parse_error=str(exc) or "parse failed",
                        )
                    )

        repo.parse_json = json.dumps([asdict(pf) for pf in parsed_files])
        save_repo(session, repo)

        # ── graph ───────────────────────────────────────────────────
        _set_status(session, repo, "graphing")
        try:
            from app.graph.builder import build_graph, reading_order  # type: ignore[import-untyped]

            all_paths = {rec["path"] for rec in file_records}
            pkg_json = next((rec for rec in file_records if rec["path"] == "package.json"), None)
            pkg_main = None
            if pkg_json and pkg_json.get("content"):
                try:
                    pkg_data = json.loads(pkg_json["content"])
                    if isinstance(pkg_data, dict) and "main" in pkg_data:
                        pkg_main = str(pkg_data["main"])
                except Exception:
                    pass

            graph_obj = build_graph(parsed_files, all_paths, package_json_main=pkg_main)
            graph_dict = asdict(graph_obj)
            graph_dict["reading_order"] = reading_order(graph_obj)
        except ImportError:
            logger.warning("Graph builder not available; storing empty graph")
            graph_dict = {"nodes": [], "edges": [], "folder_graph": {"nodes": [], "edges": []}, "entry_points": [], "reading_order": []}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Graph build failed for %s", repo_id)
            graph_dict = {"nodes": [], "edges": [], "folder_graph": {"nodes": [], "edges": []}, "entry_points": [], "reading_order": []}

        repo.graph_json = json.dumps(graph_dict)
        save_repo(session, repo)

        # ── indexing ────────────────────────────────────────────────
        _set_status(session, repo, "indexing")
        parse_by_path: dict[str, dict] = {}
        try:
            from app.rag.chunker import chunk_file
            from app.rag.indexer import index_chunks

            for pf in parsed_files:
                p_path = getattr(pf, "path", None) or (pf.get("path") if isinstance(pf, dict) else None)
                if p_path:
                    parse_by_path[p_path] = asdict(pf) if hasattr(pf, "__dataclass_fields__") else pf

            db_chunks: list[RepoChunk] = []
            for rec in file_records:
                chunks = chunk_file(
                    rec["path"],
                    rec["content"] or "",
                    rec["language"],
                    parse_info=parse_by_path.get(rec["path"]),
                )
                for c in chunks:
                    db_chunks.append(
                        RepoChunk(
                            repo_id=repo.id,
                            chunk_id=c.chunk_id,
                            path=c.path,
                            language=c.language,
                            kind=c.kind,
                            symbol_name=c.symbol_name,
                            start_line=c.start_line,
                            end_line=c.end_line,
                            text=c.text,
                            embed_text=c.embed_text,
                        )
                    )

            save_repo_chunks(session, db_chunks)
            index_chunks(repo.id, db_chunks, commit_sha=repo.commit_sha)
            repo.indexed = True
            from app.config import get_settings
            repo.embedding_model = get_settings().embedding_model
            save_repo(session, repo)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Indexing failed for %s", repo_id)

        # ── summarizing ─────────────────────────────────────────────
        _set_status(session, repo, "summarizing")
        try:
            from app.rag.summarizer import summarize_repository

            stored_files = list(
                session.scalars(select(RepoFile).where(RepoFile.repo_id == repo.id)).all()
            )
            summarize_repository(session, repo.id, stored_files, parse_by_path, stats)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Summarization failed for %s", repo_id)

        _set_status(session, repo, "ready")
    except CloneError as exc:
        logger.warning("Pipeline clone/scan failed for %s: %s", repo_id, exc.message)
        repo = session.get(Repo, repo_id)
        if repo is not None:
            _set_status(session, repo, "failed", error=exc.message)
    except Exception as exc:  # noqa: BLE001 — persist unexpected failures
        logger.exception("Pipeline failed for %s", repo_id)
        repo = session.get(Repo, repo_id)
        if repo is not None:
            _set_status(session, repo, "failed", error=str(exc) or "Analysis failed")
    finally:
        if clone_path is not None:
            cleanup(clone_path)
        session.close()
