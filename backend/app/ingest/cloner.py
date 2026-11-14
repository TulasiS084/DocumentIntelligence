"""Safe GitHub URL validation, shallow clone, size check, and cleanup."""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, Repo

from app.config import get_settings

logger = logging.getLogger(__name__)

# Strict https://github.com/<owner>/<repo> with optional trailing .git.
# Owner/repo may only use GitHub-safe characters; no query, fragment, extra path, or '..'.
GITHUB_URL_RE = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)$"
)

CLONE_DIR_PREFIX = "repo-analyzer-"


class CloneError(Exception):
    """Base class for clone failures with a stable error code."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class InvalidUrlError(CloneError):
    """The URL is not a strict public GitHub repository URL."""

    def __init__(self, message: str = "Invalid GitHub repository URL") -> None:
        super().__init__(message, "invalid_url")


class RepoNotFoundError(CloneError):
    """The repository does not exist or is private."""

    def __init__(
        self, message: str = "Repository not found or private"
    ) -> None:
        super().__init__(message, "not_found")


class CloneTimeoutError(CloneError):
    """The clone exceeded the configured timeout."""

    def __init__(self, message: str = "Clone timed out") -> None:
        super().__init__(message, "timeout")


class RepoTooLargeError(CloneError):
    """The cloned working tree exceeds the size limit."""

    def __init__(self, message: str = "Repository exceeds the size limit") -> None:
        super().__init__(message, "too_large")


@dataclass(frozen=True)
class CloneResult:
    """Filesystem path and HEAD commit of a successful clone."""

    path: str
    commit_sha: str


def validate_github_url(url: str) -> str:
    """Validate and normalize a public GitHub repository URL.

    Args:
        url: Candidate URL. Must be exactly https://github.com/<owner>/<repo>
            with an optional ``.git`` suffix.

    Returns:
        Canonical clone URL without a ``.git`` suffix.

    Raises:
        InvalidUrlError: If the URL fails the strict allow-list.
    """
    if not isinstance(url, str) or url != url.strip() or any(ch.isspace() for ch in url):
        raise InvalidUrlError()
    candidate = url[:-4] if url.endswith(".git") else url
    match = GITHUB_URL_RE.fullmatch(candidate)
    if not match:
        raise InvalidUrlError()
    owner = match.group("owner")
    repo = match.group("repo")
    if ".." in owner or ".." in repo:
        raise InvalidUrlError()
    if repo in {".", ".."} or repo.startswith(".") or repo.endswith("."):
        # Reject path tricks; GitHub also does not use leading/trailing dots.
        raise InvalidUrlError()
    return f"https://github.com/{owner}/{repo}"


def _is_under(path: Path, parent: Path) -> bool:
    """Return True if path is parent or a descendant of parent."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def directory_size_bytes(root: str | Path) -> int:
    """Sum regular file sizes under root without following symlinks outside it."""
    base = Path(root).resolve()
    total = 0
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        current = Path(dirpath)
        if not _is_under(current, base):
            dirnames.clear()
            continue
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
        for name in filenames:
            file_path = current / name
            if file_path.is_symlink():
                continue
            try:
                total += file_path.stat().st_size
            except OSError:
                logger.debug("Could not stat %s", file_path, exc_info=True)
    return total


def _rmtree_readonly(func: object, path: str, exc_info: object) -> None:
    """Clear the read-only bit then retry (needed for .git files on Windows)."""
    import gc
    import time
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)  # type: ignore[operator]
    except OSError:
        gc.collect()
        time.sleep(0.05)
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)  # type: ignore[operator]
        except OSError:
            logger.warning("Failed to delete %s", path, exc_info=True)


def cleanup(path: str | Path) -> None:
    """Safely delete a clone directory created by this module.

    Refuses to delete anything outside the configured temp directory or
    without the ``repo-analyzer-`` prefix.
    """
    import gc
    gc.collect()
    settings = get_settings()
    target = Path(path).resolve()
    temp_root = Path(settings.temp_dir).resolve()
    if not _is_under(target, temp_root):
        logger.error("Refusing to delete %s: outside temp dir %s", target, temp_root)
        return
    if not target.name.startswith(CLONE_DIR_PREFIX):
        logger.error("Refusing to delete %s: unexpected directory name", target)
        return
    if not target.exists():
        return
    logger.info("Cleaning up clone directory %s", target)
    shutil.rmtree(target, onerror=_rmtree_readonly)


def _clone_env() -> dict[str, str]:
    """Environment that never prompts for credentials."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["GCM_INTERACTIVE"] = "never"
    return env


def _do_clone(url: str, dest: str) -> Repo:
    """Perform a depth-1 clone (runs in a worker thread)."""
    return Repo.clone_from(
        url,
        dest,
        depth=1,
        single_branch=True,
        env=_clone_env(),
    )


def clone_repo(url: str) -> CloneResult:
    """Shallow-clone a public GitHub repository into a unique temp directory.

    Args:
        url: GitHub HTTPS URL.

    Returns:
        CloneResult with the working tree path and HEAD SHA.

    Raises:
        InvalidUrlError: URL failed validation.
        RepoNotFoundError: Missing or private repository.
        CloneTimeoutError: Clone exceeded the timeout.
        RepoTooLargeError: Working tree larger than the configured limit.
        CloneError: Other git failures.
    """
    canonical = validate_github_url(url)
    settings = get_settings()
    dest = tempfile.mkdtemp(prefix=CLONE_DIR_PREFIX, dir=settings.temp_dir)
    logger.info("Cloning %s into %s", canonical, dest)
    repo = None
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_clone, canonical, dest)
            try:
                repo = future.result(timeout=settings.clone_timeout_seconds)
            except FuturesTimeoutError as exc:
                logger.warning("Clone timed out for %s", canonical)
                raise CloneTimeoutError() from exc
        size = directory_size_bytes(dest)
        if size > settings.max_clone_size_bytes:
            logger.warning("Clone %s is %s bytes, over limit", canonical, size)
            raise RepoTooLargeError()
        sha = repo.head.commit.hexsha
        logger.info("Cloned %s at %s (%s bytes)", canonical, sha, size)
        return CloneResult(path=dest, commit_sha=sha)
    except CloneError:
        cleanup(dest)
        raise
    except GitCommandError as exc:
        cleanup(dest)
        stderr = (exc.stderr or str(exc)).lower()
        if (
            "not found" in stderr
            or "could not read" in stderr
            or "authentication" in stderr
            or "permission denied" in stderr
            or "repository not found" in stderr
        ):
            raise RepoNotFoundError() from exc
        logger.exception("Git clone failed for %s", canonical)
        raise CloneError("Failed to clone repository", "clone_failed") from exc
    except Exception:
        cleanup(dest)
        raise
    finally:
        if repo is not None and hasattr(repo, "close"):
            try:
                repo.close()
            except Exception:
                pass
