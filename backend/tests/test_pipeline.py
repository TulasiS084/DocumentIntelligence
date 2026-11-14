"""Pipeline status transitions, failure handling, and cleanup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.db import get_session
from app.ingest import pipeline as pipeline_mod
from app.ingest.cloner import CloneResult, CloneTimeoutError
from app.ingest.pipeline import run_pipeline
from app.models import Repo


def _make_repo(url: str = "https://github.com/octocat/Hello-World") -> str:
    session = get_session()
    try:
        repo = Repo(url=url, status="cloning")
        session.add(repo)
        session.commit()
        session.refresh(repo)
        return repo.id
    finally:
        session.close()


def _repo(repo_id: str) -> Repo:
    session = get_session()
    try:
        repo = session.get(Repo, repo_id)
        assert repo is not None
        session.expunge(repo)
        return repo
    finally:
        session.close()


def test_pipeline_success(
    temp_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clone -> scan -> ready, and cleanup is always invoked."""
    clone_dir = tmp_path / "repo-analyzer-success"
    clone_dir.mkdir()
    (clone_dir / "main.py").write_text("print(1)\n", encoding="utf-8")
    cleaned: list[str] = []

    monkeypatch.setattr(
        pipeline_mod,
        "clone_repo",
        lambda _url: CloneResult(path=str(clone_dir), commit_sha="sha1"),
    )
    monkeypatch.setattr(pipeline_mod, "cleanup", lambda path: cleaned.append(path))

    repo_id = _make_repo()
    run_pipeline(repo_id)
    repo = _repo(repo_id)
    assert repo.status == "ready"
    assert repo.commit_sha == "sha1"
    assert repo.tree_json is not None
    assert repo.error is None
    assert cleaned == [str(clone_dir)]


def test_pipeline_failure_cleans_up(
    temp_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On clone failure the row is failed and any returned path is cleaned."""
    cleaned: list[str] = []

    def boom(_url: str) -> CloneResult:
        raise CloneTimeoutError("Clone timed out")

    monkeypatch.setattr(pipeline_mod, "clone_repo", boom)
    monkeypatch.setattr(pipeline_mod, "cleanup", lambda path: cleaned.append(path))

    repo_id = _make_repo()
    run_pipeline(repo_id)
    repo = _repo(repo_id)
    assert repo.status == "failed"
    assert repo.error == "Clone timed out"
    assert cleaned == []


def test_pipeline_scan_failure_cleans_up(
    temp_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If scan raises, status is failed and cleanup still runs."""
    clone_dir = tmp_path / "repo-analyzer-failscan"
    clone_dir.mkdir()
    cleaned: list[str] = []

    monkeypatch.setattr(
        pipeline_mod,
        "clone_repo",
        lambda _url: CloneResult(path=str(clone_dir), commit_sha="sha2"),
    )
    monkeypatch.setattr(
        pipeline_mod, "scan_repository", MagicMock(side_effect=RuntimeError("scan boom"))
    )
    monkeypatch.setattr(pipeline_mod, "cleanup", lambda path: cleaned.append(path))

    repo_id = _make_repo()
    run_pipeline(repo_id)
    repo = _repo(repo_id)
    assert repo.status == "failed"
    assert "scan boom" in (repo.error or "")
    assert cleaned == [str(clone_dir)]


def test_pipeline_cache_reuse(
    temp_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a ready snapshot with the same URL and commit SHA exists, reuse it without scanning."""
    clone_dir = tmp_path / "repo-analyzer-cache"
    clone_dir.mkdir()
    (clone_dir / "index.js").write_text("console.log('hi');\n", encoding="utf-8")
    cleaned: list[str] = []

    monkeypatch.setattr(
        pipeline_mod,
        "clone_repo",
        lambda _url: CloneResult(path=str(clone_dir), commit_sha="cached-sha-123"),
    )
    monkeypatch.setattr(pipeline_mod, "cleanup", lambda path: cleaned.append(path))

    # First run scans and populates the cache
    repo_id_1 = _make_repo("https://github.com/octocat/Hello-World")
    run_pipeline(repo_id_1)
    repo1 = _repo(repo_id_1)
    assert repo1.status == "ready"
    assert repo1.tree_json is not None

    # For the second run, ensure scan_repository is NOT called
    scan_mock = MagicMock(side_effect=AssertionError("scan_repository should not be called on cache hit"))
    monkeypatch.setattr(pipeline_mod, "scan_repository", scan_mock)

    repo_id_2 = _make_repo("https://github.com/octocat/Hello-World")
    run_pipeline(repo_id_2)
    repo2 = _repo(repo_id_2)
    assert repo2.status == "ready"
    assert repo2.commit_sha == "cached-sha-123"
    assert repo2.tree_json == repo1.tree_json
    assert repo2.stats_json == repo1.stats_json
    scan_mock.assert_not_called()
    assert str(clone_dir) in cleaned


def test_pipeline_full_with_parsing(
    temp_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipeline populates repo_files, parse_json, and graph_json."""
    from app.models import RepoFile
    from sqlalchemy import select

    clone_dir = tmp_path / "repo-analyzer-full"
    clone_dir.mkdir()
    (clone_dir / "main.py").write_text("from utils import helper\nhelper()\n", encoding="utf-8")
    (clone_dir / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")

    monkeypatch.setattr(
        pipeline_mod,
        "clone_repo",
        lambda _url: CloneResult(path=str(clone_dir), commit_sha="full-sha-1"),
    )

    repo_id = _make_repo()
    run_pipeline(repo_id)
    repo = _repo(repo_id)

    assert repo.status == "ready"
    assert repo.graph_json is not None
    assert repo.parse_json is not None

    session = get_session()
    try:
        files = session.scalars(select(RepoFile).where(RepoFile.repo_id == repo_id)).all()
        paths = {f.path for f in files}
        assert "main.py" in paths
        assert "utils.py" in paths
    finally:
        session.close()


def test_pipeline_parse_error_does_not_fail(
    temp_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken file with syntax errors does not fail the pipeline."""
    import json

    clone_dir = tmp_path / "repo-analyzer-broken"
    clone_dir.mkdir()
    (clone_dir / "good.py").write_text("x = 1\n", encoding="utf-8")
    (clone_dir / "bad.py").write_text("def ( broken\n", encoding="utf-8")

    monkeypatch.setattr(
        pipeline_mod,
        "clone_repo",
        lambda _url: CloneResult(path=str(clone_dir), commit_sha="broken-sha"),
    )

    repo_id = _make_repo()
    run_pipeline(repo_id)
    repo = _repo(repo_id)

    assert repo.status == "ready"
    assert repo.parse_json is not None
    parsed = json.loads(repo.parse_json)
    assert len(parsed) == 2


def test_pipeline_cache_reprocesses_step1_incomplete(
    temp_settings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If cached repo has tree_json but no graph_json, it is reprocessed."""
    clone_dir = tmp_path / "repo-analyzer-reprocess"
    clone_dir.mkdir()
    (clone_dir / "index.js").write_text("console.log('hi');\n", encoding="utf-8")

    monkeypatch.setattr(
        pipeline_mod,
        "clone_repo",
        lambda _url: CloneResult(path=str(clone_dir), commit_sha="step1-sha"),
    )

    # Create an old Step 1 repo (ready, but graph_json is None)
    session = get_session()
    try:
        old_repo = Repo(
            url="https://github.com/octocat/Hello-World",
            commit_sha="step1-sha",
            status="ready",
            tree_json='{"name": "."}',
            stats_json='{"total_files": 1}',
            graph_json=None,  # Incomplete Step 1 cache!
        )
        session.add(old_repo)
        session.commit()
    finally:
        session.close()

    # Now run pipeline for a new repo with same URL & commit
    new_repo_id = _make_repo("https://github.com/octocat/Hello-World")
    run_pipeline(new_repo_id)
    new_repo = _repo(new_repo_id)

    # Must be reprocessed and have graph_json populated
    assert new_repo.status == "ready"
    assert new_repo.graph_json is not None

