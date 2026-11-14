"""Scanner behaviour on a fixture folder."""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.ingest.scanner import scan_repository


def _build_fixture(root: Path) -> Path:
    """Create a miniature repo covering skip rules and languages."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hi')\nprint('there')\n", encoding="utf-8")
    (root / "src" / "util.ts").write_text("export const n = 1;\n", encoding="utf-8")
    (root / "README.md").write_text("# Hello\n", encoding="utf-8")
    (root / "config.json").write_text('{"a": 1}\n', encoding="utf-8")
    (root / "notes.yml").write_text("k: v\n", encoding="utf-8")
    (root / "query.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (root / "page.html").write_text("<html></html>\n", encoding="utf-8")
    (root / "style.css").write_text("body { color: #000; }\n", encoding="utf-8")
    (root / "run.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (root / "notebook.ipynb").write_text("{}\n", encoding="utf-8")
    (root / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")
    (root / "readme.txt").write_text("plain\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "pkg.js").write_text("ignored();\n", encoding="utf-8")
    (root / "venv").mkdir()
    (root / "venv" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    (root / "dist").mkdir()
    (root / "__pycache__").mkdir()
    (root / "photo.png").write_bytes(b"\x89PNG\r\n")
    (root / "data.bin").write_bytes(b"hello\x00world")
    (root / "huge.txt").write_bytes(b"a" * (1024 * 1024 + 10))
    (root / "z_last.py").write_text("x = 1\n", encoding="utf-8")
    return root


def _by_name(node: dict, name: str) -> dict:
    children = node.get("children") or []
    match = next((child for child in children if child["name"] == name), None)
    assert match is not None, f"{name} not in {[c['name'] for c in children]}"
    return match


def test_scanner_fixture(tmp_path: Path, temp_settings: Path) -> None:
    """Ignored folders, binary/size skips, languages, and sorting."""
    fixture = _build_fixture(tmp_path / "sample")
    tree, stats = scan_repository(fixture)

    names = [child["name"] for child in tree["children"]]
    dirs = [child["name"] for child in tree["children"] if child["type"] == "dir"]
    files = [child["name"] for child in tree["children"] if child["type"] == "file"]
    assert dirs == sorted(dirs, key=str.lower)
    assert files == sorted(files, key=str.lower)
    assert names[-1] == files[-1]
    assert all(d in names[: len(dirs)] for d in dirs)

    node_modules = _by_name(tree, "node_modules")
    assert node_modules["skipped"] is True
    assert node_modules["skip_reason"] == "ignored"
    assert node_modules["children"] == []

    venv = _by_name(tree, "venv")
    assert venv["skip_reason"] == "ignored"
    dist = _by_name(tree, "dist")
    assert dist["skip_reason"] == "ignored"
    pycache = _by_name(tree, "__pycache__")
    assert pycache["skip_reason"] == "ignored"

    png = _by_name(tree, "photo.png")
    assert png["skipped"] is True
    assert png["skip_reason"] == "binary"

    binary = _by_name(tree, "data.bin")
    assert binary["skip_reason"] == "binary"

    huge = _by_name(tree, "huge.txt")
    assert huge["skipped"] is True
    assert huge["skip_reason"] == "too_large"

    app_py = _by_name(_by_name(tree, "src"), "app.py")
    assert app_py["language"] == "python"
    assert app_py["skipped"] is False
    assert app_py["loc"] == 2

    assert _by_name(_by_name(tree, "src"), "util.ts")["language"] == "typescript"
    assert _by_name(tree, "README.md")["language"] == "markdown"
    assert _by_name(tree, "config.json")["language"] == "json"
    assert _by_name(tree, "notes.yml")["language"] == "yaml"
    assert _by_name(tree, "query.sql")["language"] == "sql"
    assert _by_name(tree, "notebook.ipynb")["language"] == "jupyter"
    assert _by_name(tree, "page.html")["language"] == "html"
    assert _by_name(tree, "style.css")["language"] == "css"
    assert _by_name(tree, "run.sh")["language"] == "shell"
    assert _by_name(tree, "Dockerfile")["language"] == "dockerfile"
    assert _by_name(tree, "readme.txt")["language"] == "text"

    assert stats["skipped_count"] >= 3
    assert "python" in stats["files_by_language"]
    assert stats["total_files"] >= 1
    assert stats["total_directories"] >= 1
    # Ignored inner files are not part of the tree.
    assert stats["total_files"] == sum(
        1 for child in _all_nodes(tree) if child["type"] == "file"
    )


def _all_nodes(node: dict) -> list[dict]:
    found = [node]
    for child in node.get("children") or []:
        found.extend(_all_nodes(child))
    return found


def test_file_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_settings: Path) -> None:
    """Files beyond the analysis cap stay in the tree with limit_reached."""
    monkeypatch.setenv("MAX_FILES_ANALYZED", "2")
    get_settings.cache_clear()
    root = tmp_path / "limited"
    root.mkdir()
    (root / "a.py").write_text("a = 1\n", encoding="utf-8")
    (root / "b.py").write_text("b = 1\n", encoding="utf-8")
    (root / "c.py").write_text("c = 1\n", encoding="utf-8")
    tree, stats = scan_repository(root)
    files = {child["name"]: child for child in tree["children"]}
    skipped = [node for node in files.values() if node.get("skip_reason") == "limit_reached"]
    assert len(skipped) == 1
    assert stats["skipped_count"] == 1
    get_settings.cache_clear()
