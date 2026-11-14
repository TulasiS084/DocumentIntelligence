"""Clone, scan, persist, and always clean up the working tree."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.db import find_cached_ready, get_session, save_repo
from app.ingest.cloner import CloneError, cleanup, clone_repo
from app.ingest.scanner import scan_repository
from app.models import Repo

logger = logging.getLogger(__name__)


def _set_status(session: Session, repo: Repo, status: str, error: str | None = None) -> None:
    """Update and persist pipeline status."""
    repo.status = status
    repo.error = error
    save_repo(session, repo)
    logger.info("Repo %s status -> %s", repo.id, status)


def run_pipeline(repo_id: str) -> None:
    """Execute clone -> scan -> store for a persisted repo row.

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
            _set_status(session, repo, "ready")
            return

        _set_status(session, repo, "scanning")
        tree, stats = scan_repository(result.path)
        repo.tree_json = json.dumps(tree)
        repo.stats_json = json.dumps(stats)
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
