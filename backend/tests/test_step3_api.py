"""API integration tests for Step 3 summary and search endpoints."""

import json
from app.db import get_session, save_repo, save_repo_chunks, save_repo_summary
from app.models import Repo, RepoChunk, RepoSummary


def test_api_summary_endpoint(client):
    session = get_session()
    repo = Repo(id="repo-sum-test", url="https://github.com/foo/bar", status="ready")
    save_repo(session, repo)

    summ_json = json.dumps({
        "overview": "Overview of project",
        "stack": ["Python", "FastAPI"],
        "how_to_run": "python main.py",
        "folder_guide": {"app": "Main package"},
        "key_files": ["app/main.py"],
    })
    save_repo_summary(
        session,
        RepoSummary(repo_id="repo-sum-test", level="project", path="", text=summ_json, source="llm"),
    )
    session.close()

    resp = client.get("/api/repos/repo-sum-test/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overview"] == "Overview of project"
    assert "FastAPI" in data["stack"]
    assert data["source"] == "llm"


def test_api_search_endpoint(client):
    session = get_session()
    repo = Repo(id="repo-search-test", url="https://github.com/foo/bar", status="ready")
    save_repo(session, repo)

    chunk = RepoChunk(
        id="c1",
        repo_id="repo-search-test",
        chunk_id="app/main.py:health:1",
        path="app/main.py",
        language="python",
        kind="function",
        symbol_name="health",
        start_line=10,
        end_line=20,
        text="def health():\n    return {'status': 'ok'}",
        embed_text="app/main.py > health\ndef health(): status ok",
    )
    save_repo_chunks(session, [chunk])

    from app.rag.indexer import index_chunks
    index_chunks("repo-search-test", [chunk])
    session.close()

    body = {
        "query": "health status ok",
        "mode": "hybrid",
        "top_k": 3,
    }
    resp = client.post("/api/repos/repo-search-test/search", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo_id"] == "repo-search-test"
    assert data["mode"] == "hybrid"
    assert len(data["results"]) >= 1
    assert data["results"][0]["path"] == "app/main.py"


def test_check_llm_missing_key(monkeypatch, capsys):
    from scripts.check_llm import run_check
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.config import get_settings
    get_settings.cache_clear()

    code = run_check()
    assert code == 1
    captured = capsys.readouterr()
    assert "API key configured:  no" in captured.out
    assert "missing key" in captured.out


def test_check_llm_success(monkeypatch, capsys):
    from scripts.check_llm import run_check
    monkeypatch.setenv("GEMINI_API_KEY", "mock-test-key-12345")
    from app.config import get_settings
    get_settings.cache_clear()

    code = run_check()
    assert code == 0
    captured = capsys.readouterr()
    assert "API key configured:  yes" in captured.out
    assert "LLM OK" in captured.out
    # Guarantee no part of secret is printed
    assert "mock-test-key" not in captured.out
