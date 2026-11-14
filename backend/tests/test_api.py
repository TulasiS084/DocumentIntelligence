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


def test_file_endpoint_rejects_traversal_and_absolute(client: TestClient) -> None:
    """Path traversal ('..') and absolute paths are rejected with HTTP 400."""
    repo_id = "00000000-0000-0000-0000-000000000000"
    for bad_path in ["../secret.txt", "../../etc/passwd", "/etc/passwd", "\\windows\\win.ini", "C:/test.py"]:
        resp = client.get(f"/api/repos/{repo_id}/file?path={bad_path}")
        assert resp.status_code == 400


def test_file_endpoint_success_and_not_found(client: TestClient) -> None:
    """Fetch stored file content from repo_files."""
    from app.db import get_session
    from app.models import Repo, RepoFile

    session = get_session()
    try:
        repo = Repo(
            url="https://github.com/octocat/Hello-World",
            status="ready",
            tree_json='{"name": "."}',
        )
        session.add(repo)
        session.commit()
        session.refresh(repo)

        repo_file = RepoFile(
            repo_id=repo.id,
            path="src/main.py",
            language="python",
            loc=10,
            content="print('hello')\n",
        )
        session.add(repo_file)
        session.commit()
        repo_id = repo.id
    finally:
        session.close()

    # Success
    res = client.get(f"/api/repos/{repo_id}/file?path=src/main.py")
    assert res.status_code == 200
    data = res.json()
    assert data["path"] == "src/main.py"
    assert data["content"] == "print('hello')\n"
    assert data["loc"] == 10

    # Unknown file in ready repo -> 404
    missing_res = client.get(f"/api/repos/{repo_id}/file?path=nonexistent.py")
    assert missing_res.status_code == 404


def test_graph_overview_hides_tests_by_default(client: TestClient) -> None:
    """Overview endpoint hides test, doc, and config folders unless include_hidden=true."""
    import json
    from app.db import get_session
    from app.models import Repo

    graph_data = {
        "nodes": [
            {"id": "src/main.py", "label": "main.py", "folder": "src", "role": "entry", "loc": 10},
            {"id": "tests/test_main.py", "label": "test_main.py", "folder": "tests", "role": "test", "loc": 5},
        ],
        "edges": [
            {"source": "tests/test_main.py", "target": "src/main.py", "kind": "test_of"},
        ],
        "entry_points": ["src/main.py"],
        "folder_graph": {
            "nodes": [
                {"id": "src", "label": "src", "role": "entry", "summary": "Core package", "file_count": 1, "loc": 10},
                {"id": "tests", "label": "tests", "role": "test", "summary": "Test suite", "file_count": 1, "loc": 5},
            ],
            "edges": [
                {"source": "tests", "target": "src", "kind": "test_of", "count": 1},
            ],
        },
        "reading_order": ["src/main.py"],
    }

    session = get_session()
    try:
        repo = Repo(
            url="https://github.com/octocat/Hello-World",
            status="ready",
            tree_json='{"name": "."}',
            graph_json=json.dumps(graph_data),
        )
        session.add(repo)
        session.commit()
        session.refresh(repo)
        repo_id = repo.id
    finally:
        session.close()

    # By default, tests are hidden
    res_default = client.get(f"/api/repos/{repo_id}/graph/overview")
    assert res_default.status_code == 200
    folder_ids = [n["id"] for n in res_default.json()["nodes"]]
    assert "src" in folder_ids
    assert "tests" not in folder_ids

    # With include_hidden=true
    res_hidden = client.get(f"/api/repos/{repo_id}/graph/overview?include_hidden=true")
    assert res_hidden.status_code == 200
    folder_ids_all = [n["id"] for n in res_hidden.json()["nodes"]]
    assert "src" in folder_ids_all
    assert "tests" in folder_ids_all

    # Node detail
    node_res = client.get(f"/api/repos/{repo_id}/graph/node?id=src/main.py")
    assert node_res.status_code == 200
    assert node_res.json()["id"] == "src/main.py"

    # Reading order
    ro_res = client.get(f"/api/repos/{repo_id}/reading-order")
    assert ro_res.status_code == 200
    assert ro_res.json()["reading_order"] == ["src/main.py"]

