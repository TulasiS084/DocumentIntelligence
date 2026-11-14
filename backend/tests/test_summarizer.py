"""Unit tests for layered summarizer with LLM calls and deterministic fallbacks."""

from app.db import get_repo_summary, get_session
from app.models import RepoFile
from app.rag.summarizer import (
    _clean_json_response,
    _deterministic_file_summary,
    _deterministic_project_summary,
    summarize_repository,
)


def test_clean_json_response():
    raw_markdown = "```json\n{\n  \"overview\": \"Great project\"\n}\n```"
    cleaned = _clean_json_response(raw_markdown)
    assert cleaned == '{\n  "overview": "Great project"\n}'


def test_deterministic_file_summary():
    file_info = {
        "path": "app/db.py",
        "language": "python",
        "loc": 100,
        "symbols": [{"name": "init_engine"}, {"name": "get_session"}],
        "imports": [{"module": "sqlalchemy"}],
    }
    summ = _deterministic_file_summary(file_info)
    assert "app/db.py" in summ
    assert "init_engine" in summ
    assert "sqlalchemy" in summ


def test_deterministic_project_summary():
    files = [
        RepoFile(repo_id="r1", path="main.py", language="python", loc=50, content="print('hello')"),
        RepoFile(repo_id="r1", path="README.md", language="markdown", loc=20, content="# RepoLens\n\nVisual repo analyzer tool for engineers."),
    ]
    stats = {"languages": {"python": 50, "markdown": 20}, "total_loc": 70, "total_files": 2}
    summ = _deterministic_project_summary(files, stats, readme_content=files[1].content)
    assert "overview" in summ
    assert "Visual repo analyzer tool" in summ["overview"]
    assert "main.py" in summ["key_files"]


def test_summarize_repository_persists(temp_settings):
    session = get_session()
    repo_id = "test_summ_repo"
    files = [
        RepoFile(repo_id=repo_id, path="src/index.js", language="javascript", loc=40, content="console.log(1);"),
    ]
    for f in files:
        session.add(f)
    session.commit()

    parse_results = {"src/index.js": {"path": "src/index.js", "language": "javascript", "loc": 40}}
    stats = {"languages": {"javascript": 40}, "total_loc": 40, "total_files": 1}

    proj = summarize_repository(session, repo_id, files, parse_results, stats)
    assert "overview" in proj

    # Check database persistence
    file_s = get_repo_summary(session, repo_id, "file", "src/index.js")
    assert file_s is not None
    proj_s = get_repo_summary(session, repo_id, "project", "")
    assert proj_s is not None
    session.close()
