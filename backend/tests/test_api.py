"""HTTP API tests for health, validation, and missing resources."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    """Health endpoint reports ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://github.com.evil.com/a/b",
        "https://gitlab.com/a/b",
        "https://github.com/a/b/extra",
        "",
        "   ",
        "not-a-url",
    ],
)
def test_bad_url_returns_400(client: TestClient, bad_url: str) -> None:
    """Non-GitHub, empty, whitespace, or malformed URLs are rejected with HTTP 400."""
    response = client.post("/api/repos", json={"url": bad_url})
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body
    assert body.get("code") == "invalid_url"


def test_unknown_repo_returns_404(client: TestClient) -> None:
    """Status and tree for an unknown id are 404."""
    missing = "00000000-0000-0000-0000-000000000000"
    status = client.get(f"/api/repos/{missing}/status")
    assert status.status_code == 404
    tree = client.get(f"/api/repos/{missing}/tree")
    assert tree.status_code == 404


def test_tree_not_ready_returns_409(client: TestClient, monkeypatch) -> None:
    """Fetching the tree before the pipeline finishes is a 409."""
    monkeypatch.setattr("app.main.run_pipeline", lambda _repo_id: None)
    created = client.post(
        "/api/repos", json={"url": "https://github.com/octocat/Hello-World"}
    )
    assert created.status_code == 202
    repo_id = created.json()["repo_id"]
    tree = client.get(f"/api/repos/{repo_id}/tree")
    assert tree.status_code == 409
