"""URL validation and clone error-mapping tests (git clone is mocked)."""

from __future__ import annotations

from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import GitCommandError

from app.ingest import cloner
from app.ingest.cloner import (
    CloneTimeoutError,
    InvalidUrlError,
    RepoNotFoundError,
    RepoTooLargeError,
    clone_repo,
    validate_github_url,
)


VALID_URLS = [
    "https://github.com/octocat/Hello-World",
    "https://github.com/octocat/Hello-World.git",
    "https://github.com/a/b",
    "https://github.com/Some-User/my_repo.name",
]


@pytest.mark.parametrize("url", VALID_URLS)
def test_valid_urls_pass(url: str) -> None:
    """Accepted URLs normalize to https://github.com/owner/repo."""
    result = validate_github_url(url)
    assert result.startswith("https://github.com/")
    assert result.count("/") == 4
    assert not result.endswith(".git")


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/octocat/Hello-World",
        "https://gitlab.com/octocat/Hello-World",
        "https://github.com.evil.com/octocat/Hello-World",
        "https://evilgithub.com/octocat/Hello-World",
        "https://www.github.com/octocat/Hello-World",
        "https://github.com/octocat/Hello-World/extra",
        "https://github.com/octocat/Hello-World/tree/main",
        "https://github.com/octocat/Hello-World?foo=1",
        "https://github.com/octocat/Hello-World#readme",
        "https://github.com/octocat/../Hello-World",
        "https://github.com/oc..tocat/Hello-World",
        "https://github.com/octocat/Hello..World",
        "https://github.com/octocat/Hello-World ",
        " https://github.com/octocat/Hello-World",
        "https://github.com/octocat/Hello World",
        "github.com/octocat/Hello-World",
        "https://github.com/octocat",
        "https://github.com/",
        "",
    ],
)
def test_invalid_urls_rejected(url: str) -> None:
    """Hosts, extra path, queries, fragments, '..', and whitespace are rejected."""
    with pytest.raises(InvalidUrlError):
        validate_github_url(url)


def test_clone_repo_success(temp_settings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A mocked clone returns path and SHA and does not delete the dest on success."""

    def fake_clone(url: str, dest: str, **_kwargs: object) -> MagicMock:
        Path(dest, "README.md").write_text("hi\n", encoding="utf-8")
        repo = MagicMock()
        repo.head.commit.hexsha = "abc123def456"
        return repo

    monkeypatch.setattr(cloner, "_do_clone", fake_clone)
    result = clone_repo("https://github.com/octocat/Hello-World")
    assert result.commit_sha == "abc123def456"
    assert Path(result.path).is_dir()
    cloner.cleanup(result.path)


def test_clone_not_found(temp_settings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git 'not found' maps to RepoNotFoundError and dest is removed."""

    def fake_clone(url: str, dest: str, **_kwargs: object) -> MagicMock:
        raise GitCommandError(["git", "clone"], 128, stderr="ERROR: Repository not found.")

    monkeypatch.setattr(cloner, "_do_clone", fake_clone)
    with pytest.raises(RepoNotFoundError):
        clone_repo("https://github.com/octocat/does-not-exist")
    leftovers = list(temp_settings.glob("repo-analyzer-*"))
    assert leftovers == []


def test_clone_timeout(temp_settings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TimeoutError from the worker is mapped to CloneTimeoutError."""

    class ImmediateTimeout:
        def __init__(self, max_workers: int) -> None:
            pass

        def __enter__(self) -> "ImmediateTimeout":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def submit(self, fn: object, *args: object, **kwargs: object) -> MagicMock:
            future = MagicMock()
            future.result.side_effect = FuturesTimeoutError()
            return future

    monkeypatch.setattr(cloner, "ThreadPoolExecutor", ImmediateTimeout)
    with pytest.raises(CloneTimeoutError):
        clone_repo("https://github.com/octocat/Hello-World")


def test_clone_too_large(temp_settings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Clones larger than the size limit are deleted and rejected."""

    def fake_clone(url: str, dest: str, **_kwargs: object) -> MagicMock:
        Path(dest, "fat.bin").write_bytes(b"x" * 100)
        repo = MagicMock()
        repo.head.commit.hexsha = "deadbeef"
        return repo

    monkeypatch.setattr(cloner, "_do_clone", fake_clone)
    monkeypatch.setattr(cloner, "directory_size_bytes", lambda _path: 10**12)
    with pytest.raises(RepoTooLargeError):
        clone_repo("https://github.com/octocat/Hello-World")
    leftovers = list(temp_settings.glob("repo-analyzer-*"))
    assert leftovers == []
