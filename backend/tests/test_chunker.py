"""Unit tests for semantic chunker across code, docs, notebooks, configs, and data."""

from app.rag.chunker import build_file_chunks, chunk_file


def test_chunk_python_functions_and_classes():
    py_code = (
        'def add(a: int, b: int) -> int:\n'
        '    """Add two numbers."""\n'
        '    return a + b\n\n'
        'class Calculator:\n'
        '    """Simple calculator."""\n'
        '    def multiply(self, a, b):\n'
        '        return a * b\n'
    )
    parse_info = {
        "kind": "code",
        "symbols": [
            {"name": "add", "kind": "function", "start_line": 1, "end_line": 3},
            {"name": "Calculator", "kind": "class", "start_line": 5, "end_line": 8},
            {"name": "Calculator.multiply", "kind": "method", "start_line": 7, "end_line": 8},
        ],
    }
    chunks = chunk_file("calc.py", py_code, "python", parse_info=parse_info, repo_id="r1")
    assert len(chunks) >= 2
    sym_names = {c.symbol_name for c in chunks if c.symbol_name}
    assert "add" in sym_names
    assert any(c.kind in ("function", "method", "class") for c in chunks)
    for c in chunks:
        assert c.path == "calc.py"
        assert c.chunk_id.startswith("calc.py:")
        assert c.start_line >= 1
        assert c.end_line >= c.start_line


def test_chunk_window_splitting_on_long_function():
    long_code = "\n".join([f"    line_{i} = {i}" for i in range(120)])
    fn_code = f"def giant_function():\n{long_code}\n"
    parse_info = {
        "kind": "code",
        "symbols": [{"name": "giant_function", "kind": "function", "start_line": 1, "end_line": 122}],
    }
    chunks = chunk_file("big.py", fn_code, "python", parse_info=parse_info, repo_id="r1")
    assert len(chunks) > 1
    # Check 60-line windowing with 10-line overlap
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 60
    assert chunks[1].start_line == 51


def test_chunk_markdown_by_headings():
    md_content = (
        "# Main Title\nWelcome to RepoLens.\n\n"
        "## Installation\nRun pip install.\n\n"
        "## Usage\nRun uvicorn app.main:app.\n"
    )
    chunks = chunk_file("README.md", md_content, "markdown", parse_info={"kind": "doc"}, repo_id="r1")
    assert len(chunks) >= 2
    titles = [c.symbol_name for c in chunks if c.symbol_name]
    assert any("Installation" in (t or "") for t in titles)
    assert any("Usage" in (t or "") for t in titles)


def test_chunk_config_file():
    cfg_content = '{\n  "name": "repolens",\n  "version": "1.0.0"\n}'
    chunks = chunk_file(
        "package.json",
        cfg_content,
        "json",
        parse_info={"kind": "config", "summary_hint": "repolens v1.0.0"},
        repo_id="r1",
    )
    assert len(chunks) == 1
    assert chunks[0].kind == "config"
    assert "repolens" in chunks[0].text


def test_chunk_data_schema():
    csv_content = "id,name,age\n1,Alice,30\n2,Bob,25\n"
    chunks = chunk_file(
        "users.csv",
        csv_content,
        "csv",
        parse_info={"kind": "data", "summary_hint": "Columns: id, name, age"},
        repo_id="r1",
    )
    assert len(chunks) == 1
    assert chunks[0].kind == "schema"
    assert "Columns: id, name, age" in chunks[0].text
