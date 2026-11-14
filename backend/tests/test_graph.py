"""Unit tests for the graph builder (edges, roles, folders, cycles, reading order)."""

from __future__ import annotations

from app.graph.builder import (
    build_graph,
    cycles,
    dependencies_of,
    dependents_of,
    entry_points,
    most_connected,
    reading_order,
    resolve_import,
    transitive_dependents_count,
)
from app.ingest.parsers.models import CallInfo, ImportInfo, ParsedFile, SymbolDef


def test_import_resolution_python() -> None:
    """Resolve relative and absolute Python imports, including src/ layout and __init__.py."""
    all_paths = {
        "src/app/main.py",
        "src/app/utils.py",
        "src/app/models/__init__.py",
        "src/app/models/user.py",
    }
    # Relative import from main.py: from .utils import x
    res1 = resolve_import("utils", is_relative=True, source_path="src/app/main.py", all_paths=all_paths)
    assert res1 == "src/app/utils.py"

    # Absolute import: app.models.user
    res2 = resolve_import("app.models.user", is_relative=False, source_path="src/app/main.py", all_paths=all_paths)
    assert res2 == "src/app/models/user.py"

    # Unresolved external package: pandas
    res3 = resolve_import("pandas", is_relative=False, source_path="src/app/main.py", all_paths=all_paths)
    assert res3 is None


def test_import_resolution_js_ts() -> None:
    """Resolve JS/TS imports with ./, ../ and /index resolution."""
    all_paths = {
        "frontend/src/App.tsx",
        "frontend/src/components/Button.tsx",
        "frontend/src/utils/index.ts",
    }
    # ./components/Button -> frontend/src/components/Button.tsx
    res1 = resolve_import("./components/Button", is_relative=True, source_path="frontend/src/App.tsx", all_paths=all_paths)
    assert res1 == "frontend/src/components/Button.tsx"

    # ./utils -> frontend/src/utils/index.ts
    res2 = resolve_import("./utils", is_relative=True, source_path="frontend/src/App.tsx", all_paths=all_paths)
    assert res2 == "frontend/src/utils/index.ts"


def test_graph_builder_python_package() -> None:
    """Test full graph construction for a Python package."""
    pf_main = ParsedFile(
        path="src/main.py",
        language="python",
        kind="code",
        imports=[
            ImportInfo(module="utils", names=["helper"], is_relative=True),
            ImportInfo(module="numpy", names=[], is_relative=False),  # external
        ],
        calls=[CallInfo(callee="helper", line=5)],
        summary_hint="Main entry point",
    )
    pf_utils = ParsedFile(
        path="src/utils.py",
        language="python",
        kind="code",
        symbols=[SymbolDef(name="helper", kind="function", start_line=1, end_line=3)],
        summary_hint="Helper utilities",
    )
    pf_test = ParsedFile(
        path="tests/test_main.py",
        language="python",
        kind="test",
        imports=[ImportInfo(module="src.main", names=[], is_relative=False)],
        summary_hint="Tests for main",
    )

    all_paths = {"src/main.py", "src/utils.py", "tests/test_main.py"}
    graph = build_graph([pf_main, pf_utils, pf_test], all_paths)

    # Assert exact nodes
    node_ids = {n.id for n in graph.nodes}
    assert node_ids == all_paths

    # Roles: main.py -> entry, utils.py -> helper, test_main.py -> test
    node_map = {n.id: n for n in graph.nodes}
    assert node_map["src/main.py"].role == "entry"
    assert node_map["src/utils.py"].role == "helper"
    assert node_map["tests/test_main.py"].role == "test"

    # External packages tracked
    assert "numpy" in node_map["src/main.py"].external

    # Edges
    import_edges = [e for e in graph.edges if e.kind == "import"]
    assert any(e.source == "src/main.py" and e.target == "src/utils.py" for e in import_edges)

    # Call edges
    call_edges = [e for e in graph.edges if e.kind == "call"]
    assert any(e.source == "src/main.py" and e.target == "src/utils.py" for e in call_edges)

    # Test-of edge
    test_edges = [e for e in graph.edges if e.kind == "test_of"]
    assert any(e.source == "tests/test_main.py" for e in test_edges)

    # Folder graph
    folder_ids = {f.id for f in graph.folder_graph.nodes}
    assert "src" in folder_ids
    assert "tests" in folder_ids


def test_data_and_config_edges() -> None:
    """Test data_read, config_ref, and doc_link edge kinds."""
    pf_nb = ParsedFile(
        path="notebooks/train.ipynb",
        language="jupyter",
        kind="notebook",
        references=["data/train.csv"],
        summary_hint="Training notebook",
    )
    pf_csv = ParsedFile(
        path="data/train.csv",
        language="csv",
        kind="data",
        summary_hint="Data file",
    )
    pf_docker = ParsedFile(
        path="Dockerfile",
        language="dockerfile",
        kind="config",
        references=["src/main.py"],
        summary_hint="Docker config",
    )
    pf_code = ParsedFile(
        path="src/main.py",
        language="python",
        kind="code",
        summary_hint="Main code",
    )
    pf_doc = ParsedFile(
        path="README.md",
        language="markdown",
        kind="doc",
        references=["src/main.py"],
        summary_hint="Read me",
    )

    all_paths = {"notebooks/train.ipynb", "data/train.csv", "Dockerfile", "src/main.py", "README.md"}
    graph = build_graph([pf_nb, pf_csv, pf_docker, pf_code, pf_doc], all_paths)

    edge_kinds = {e.kind for e in graph.edges}
    assert "data_read" in edge_kinds
    assert "config_ref" in edge_kinds
    assert "doc_link" in edge_kinds

    # Assert exact edge matches
    assert any(e.source == "notebooks/train.ipynb" and e.target == "data/train.csv" and e.kind == "data_read" for e in graph.edges)
    assert any(e.source == "Dockerfile" and e.target == "src/main.py" and e.kind == "config_ref" for e in graph.edges)
    assert any(e.source == "README.md" and e.target == "src/main.py" and e.kind == "doc_link" for e in graph.edges)


def test_cycle_detection() -> None:
    """Detect circular import cycles (a -> b -> c -> a)."""
    pf_a = ParsedFile(path="a.py", language="python", kind="code", imports=[ImportInfo(module="b", names=[], is_relative=True)])
    pf_b = ParsedFile(path="b.py", language="python", kind="code", imports=[ImportInfo(module="c", names=[], is_relative=True)])
    pf_c = ParsedFile(path="c.py", language="python", kind="code", imports=[ImportInfo(module="a", names=[], is_relative=True)])

    all_paths = {"a.py", "b.py", "c.py"}
    graph = build_graph([pf_a, pf_b, pf_c], all_paths)

    found_cycles = cycles(graph)
    assert len(found_cycles) > 0
    cycle_nodes = set(found_cycles[0])
    assert "a.py" in cycle_nodes
    assert "b.py" in cycle_nodes
    assert "c.py" in cycle_nodes


def test_graph_queries() -> None:
    """Test dependents_of, dependencies_of, transitive_dependents_count, and reading_order."""
    pf_main = ParsedFile(path="main.py", language="python", kind="code", imports=[ImportInfo(module="core", names=[], is_relative=True)])
    pf_core = ParsedFile(path="core.py", language="python", kind="code", imports=[ImportInfo(module="utils", names=[], is_relative=True)])
    pf_utils = ParsedFile(path="utils.py", language="python", kind="code")

    all_paths = {"main.py", "core.py", "utils.py"}
    graph = build_graph([pf_main, pf_core, pf_utils], all_paths)

    assert dependencies_of(graph, "main.py") == ["core.py"]
    assert dependents_of(graph, "utils.py") == ["core.py"]

    # transitive dependents of utils.py: both core.py and main.py depend on utils.py
    assert transitive_dependents_count(graph, "utils.py") == 2
    assert transitive_dependents_count(graph, "main.py") == 0

    order = reading_order(graph)
    assert len(order) >= 1
    assert "main.py" in order
