"""Build a dependency graph from parsed file results.

Resolves imports, detects roles, constructs file-level and folder-level
graphs, and exposes query helpers.  No LLM calls — everything is
deterministic.
"""

from __future__ import annotations

import logging
import posixpath
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.ingest.parsers.models import ParsedFile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    """A single file in the dependency graph."""

    id: str  # = path (posix relative)
    label: str
    folder: str
    language: str | None
    loc: int
    kind: str  # code|notebook|doc|config|sql|data|test
    role: str  # entry|core|helper|test|other
    in_degree: int = 0
    out_degree: int = 0
    summary: str = ""
    external: list[str] = field(default_factory=list)


@dataclass
class GraphEdge:
    """A directed dependency between two files."""

    source: str
    target: str
    kind: str  # import|call|data_read|config_ref|doc_link|test_of
    weight: int = 1


@dataclass
class FolderNode:
    """A folder in the aggregated folder graph."""

    id: str
    label: str
    files: list[str] = field(default_factory=list)
    role: str = "other"
    summary: str = ""
    file_count: int = 0
    loc: int = 0


@dataclass
class FolderEdge:
    """An aggregated edge between two folders."""

    source: str
    target: str
    kind: str
    count: int = 1


@dataclass
class FolderGraph:
    """Folder-level view of the repository."""

    nodes: list[FolderNode] = field(default_factory=list)
    edges: list[FolderEdge] = field(default_factory=list)


@dataclass
class RepoGraph:
    """Complete dependency graph for a repository."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    folder_graph: FolderGraph = field(default_factory=FolderGraph)


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------

_JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")


def resolve_import(
    module: str,
    is_relative: bool,
    source_path: str,
    all_paths: set[str],
) -> str | None:
    """Resolve an import string to a file path in *all_paths*.

    Returns ``None`` for external/unresolvable packages.
    """
    ext = posixpath.splitext(source_path)[1].lower()

    if ext in (".py",) or (is_relative and ext not in _JS_EXTENSIONS):
        return _resolve_python(module, is_relative, source_path, all_paths)

    if ext in _JS_EXTENSIONS:
        return _resolve_js(module, is_relative, source_path, all_paths)

    return None


def _resolve_python(
    module: str,
    is_relative: bool,
    source_path: str,
    all_paths: set[str],
) -> str | None:
    """Resolve a Python import to a path in *all_paths*."""
    source_dir = posixpath.dirname(source_path)

    if is_relative:
        # Relative: ``from .foo import bar`` → sibling foo.py or foo/__init__.py
        parts = module.split(".")
        base = posixpath.join(source_dir, *parts) if parts and parts[0] else source_dir
        return _try_python_candidates(base, all_paths)

    # Absolute import: ``import app.config``
    parts = module.split(".")
    base = "/".join(parts)
    result = _try_python_candidates(base, all_paths)
    if result:
        return result

    # Try with src/ prefix
    result = _try_python_candidates("src/" + base, all_paths)
    if result:
        return result

    return None


def _try_python_candidates(base: str, all_paths: set[str]) -> str | None:
    """Check common Python file locations for *base*."""
    candidates = [
        base + ".py",
        base + "/__init__.py",
        base,
    ]
    for candidate in candidates:
        normed = posixpath.normpath(candidate)
        if normed in all_paths:
            return normed
    return None


def _resolve_js(
    module: str,
    is_relative: bool,
    source_path: str,
    all_paths: set[str],
) -> str | None:
    """Resolve a JS/TS import to a path in *all_paths*."""
    if not is_relative:
        return None  # bare specifier → external package

    source_dir = posixpath.dirname(source_path)
    base = posixpath.normpath(posixpath.join(source_dir, module))

    # Exact match (already has extension)
    if base in all_paths:
        return base

    # Try appending extensions
    for ext in _JS_EXTENSIONS:
        candidate = base + ext
        if candidate in all_paths:
            return candidate

    # Index fallback
    for ext in _JS_EXTENSIONS:
        candidate = base + "/index" + ext
        if candidate in all_paths:
            return candidate

    return None


# ---------------------------------------------------------------------------
# Edge building helpers
# ---------------------------------------------------------------------------

_DATA_EXTENSIONS = {".csv", ".json", ".sql", ".db", ".sqlite", ".sqlite3"}

_ENTRY_BASENAMES = {
    "main.py", "app.py", "manage.py",
    "server.js", "index.js", "server.ts", "index.ts",
}

_HELPER_BASENAMES = {
    "utils", "helpers", "common", "lib", "constants", "types", "base",
}

_TEST_PATTERNS = re.compile(
    r"(^test_|_test$|\.test$|\.spec$|^tests$|^__tests__$)",
    re.IGNORECASE,
)


def _is_test_path(path: str) -> bool:
    """Return True if *path* looks like a test file by name or location."""
    basename = posixpath.basename(path)
    stem = posixpath.splitext(basename)[0]
    if _TEST_PATTERNS.search(stem):
        return True
    parts = path.split("/")
    for part in parts:
        if part in ("tests", "__tests__", "test"):
            return True
    return False


def _infer_test_of(path: str, all_paths: set[str]) -> str | None:
    """If *path* is a test file, guess the source it tests by naming."""
    basename = posixpath.basename(path)
    stem, ext = posixpath.splitext(basename)

    # test_x.py → x.py
    if stem.startswith("test_"):
        candidate_stem = stem[5:]
    # x_test.py → x.py
    elif stem.endswith("_test"):
        candidate_stem = stem[:-5]
    # x.test.ts → x.ts  /  x.spec.ts → x.ts
    elif ".test" in basename or ".spec" in basename:
        candidate_stem = stem.split(".")[0]
        # try with original extension
        ext_options = [ext, ".ts", ".tsx", ".js", ".jsx"]
        src_dir = posixpath.dirname(path)
        # Check parent dir (tests/ → src/)
        for candidate_dir in (src_dir, posixpath.dirname(src_dir)):
            for try_ext in ext_options:
                candidate = posixpath.normpath(
                    posixpath.join(candidate_dir, candidate_stem + try_ext)
                )
                if candidate in all_paths:
                    return candidate
        return None
    else:
        return None

    # Try same directory and parent
    src_dir = posixpath.dirname(path)
    for candidate_dir in (src_dir, posixpath.dirname(src_dir)):
        candidate = posixpath.normpath(
            posixpath.join(candidate_dir, candidate_stem + ext)
        )
        if candidate in all_paths:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Core graph builder
# ---------------------------------------------------------------------------


def build_graph(
    parsed_files: list[ParsedFile],
    all_paths: set[str] | None = None,
    package_json_main: str | None = None,
) -> RepoGraph:
    """Build the complete dependency graph from parser outputs.

    Parameters
    ----------
    parsed_files:
        Outputs produced by file parsers.
    all_paths:
        Every file path in the repository (used for import resolution).
    package_json_main:
        Value of the ``main`` field in the root ``package.json``, if any.
    """
    if all_paths is None:
        all_paths = {pf.path for pf in parsed_files}

    graph = RepoGraph()

    # Index parsed files by path
    file_by_path: dict[str, ParsedFile] = {pf.path: pf for pf in parsed_files}

    # Index symbols by name → defining file path
    symbol_to_file: dict[str, set[str]] = defaultdict(set)
    for pf in parsed_files:
        for sym in pf.symbols:
            symbol_to_file[sym.name].add(pf.path)

    # ------------------------------------------------------------------
    # Build edges
    # ------------------------------------------------------------------
    edges: list[GraphEdge] = []
    # Track resolved imports per file for call-edge matching
    file_imports: dict[str, set[str]] = defaultdict(set)  # source → set of targets
    # Track unresolved (external) modules per file
    file_externals: dict[str, list[str]] = defaultdict(list)

    for pf in parsed_files:
        # --- import edges ---
        for imp in pf.imports:
            target = resolve_import(imp.module, imp.is_relative, pf.path, all_paths)
            if target and target != pf.path:
                edges.append(GraphEdge(source=pf.path, target=target, kind="import"))
                file_imports[pf.path].add(target)
            elif target is None:
                file_externals[pf.path].append(imp.module)

        # --- call edges ---
        call_counts: dict[str, int] = Counter()
        for call in pf.calls:
            callee = call.callee.split(".")[-1]  # strip module prefix
            defining_files = symbol_to_file.get(callee, set())
            for def_file in defining_files:
                if def_file != pf.path and def_file in file_imports[pf.path]:
                    call_counts[def_file] += 1
        for target_path, count in call_counts.items():
            edges.append(
                GraphEdge(source=pf.path, target=target_path, kind="call", weight=count)
            )

        # --- data_read edges ---
        for ref in pf.references:
            ref_ext = posixpath.splitext(ref)[1].lower()
            if ref_ext in _DATA_EXTENSIONS:
                target_path = None
                normed = posixpath.normpath(
                    posixpath.join(posixpath.dirname(pf.path), ref)
                )
                if ref in all_paths and ref != pf.path:
                    target_path = ref
                elif normed in all_paths and normed != pf.path:
                    target_path = normed
                if target_path:
                    edges.append(
                        GraphEdge(source=pf.path, target=target_path, kind="data_read")
                    )

        # --- config_ref edges ---
        if pf.kind == "config":
            for ref in pf.references:
                target_path = None
                normed = posixpath.normpath(
                    posixpath.join(posixpath.dirname(pf.path), ref)
                )
                if ref in all_paths and ref != pf.path:
                    target_path = ref
                elif normed in all_paths and normed != pf.path:
                    target_path = normed
                if target_path:
                    edges.append(
                        GraphEdge(source=pf.path, target=target_path, kind="config_ref")
                    )

        # --- doc_link edges ---
        if pf.kind == "doc":
            for ref in pf.references:
                target_path = None
                normed = posixpath.normpath(
                    posixpath.join(posixpath.dirname(pf.path), ref)
                )
                if ref in all_paths and ref != pf.path:
                    target_path = ref
                elif normed in all_paths and normed != pf.path:
                    target_path = normed
                if target_path:
                    edges.append(
                        GraphEdge(source=pf.path, target=target_path, kind="doc_link")
                    )

    # --- test_of edges ---
    for pf in parsed_files:
        if _is_test_path(pf.path):
            # By naming convention
            src = _infer_test_of(pf.path, all_paths)
            if src:
                edges.append(
                    GraphEdge(source=pf.path, target=src, kind="test_of")
                )
            # By import: test imports source
            for imp_target in file_imports.get(pf.path, set()):
                if not _is_test_path(imp_target):
                    edges.append(
                        GraphEdge(
                            source=pf.path, target=imp_target, kind="test_of",
                        )
                    )

    # Deduplicate edges (same source+target+kind → keep highest weight)
    edge_key: dict[tuple[str, str, str], GraphEdge] = {}
    for e in edges:
        key = (e.source, e.target, e.kind)
        if key not in edge_key or e.weight > edge_key[key].weight:
            edge_key[key] = e
    edges = list(edge_key.values())

    # ------------------------------------------------------------------
    # Compute degrees
    # ------------------------------------------------------------------
    in_deg: dict[str, int] = Counter()
    out_deg: dict[str, int] = Counter()
    for e in edges:
        out_deg[e.source] += 1
        in_deg[e.target] += 1

    # ------------------------------------------------------------------
    # Build nodes & assign roles
    # ------------------------------------------------------------------
    nodes: list[GraphNode] = []
    entry_points_list: list[str] = []

    for pf in parsed_files:
        basename = posixpath.basename(pf.path)
        folder = posixpath.dirname(pf.path) or "."
        in_d = in_deg.get(pf.path, 0)
        out_d = out_deg.get(pf.path, 0)

        role = _assign_role(
            path=pf.path,
            kind=pf.kind,
            basename=basename,
            symbols=pf.symbols,
            in_degree=in_d,
            out_degree=out_d,
            package_json_main=package_json_main,
        )

        if role == "entry":
            entry_points_list.append(pf.path)

        # De-duplicate externals
        externals = sorted(set(file_externals.get(pf.path, [])))

        node = GraphNode(
            id=pf.path,
            label=basename,
            folder=folder,
            language=pf.language,
            loc=_loc_from_parsed(pf),
            kind=pf.kind,
            role=role,
            in_degree=in_d,
            out_degree=out_d,
            summary=pf.summary_hint,
            external=externals,
        )
        nodes.append(node)

    # ------------------------------------------------------------------
    # Folder-level graph
    # ------------------------------------------------------------------
    folder_graph = _build_folder_graph(nodes, edges)

    graph.nodes = nodes
    graph.edges = edges
    graph.entry_points = sorted(entry_points_list)
    graph.folder_graph = folder_graph

    logger.info(
        "Graph built: %d nodes, %d edges, %d entry points",
        len(nodes),
        len(edges),
        len(entry_points_list),
    )
    return graph


# ---------------------------------------------------------------------------
# Role assignment
# ---------------------------------------------------------------------------


def _assign_role(
    *,
    path: str,
    kind: str,
    basename: str,
    symbols: list,
    in_degree: int,
    out_degree: int,
    package_json_main: str | None,
) -> str:
    """Deterministic role for a file."""
    # Test detection first (overrides entry)
    if _is_test_path(path):
        return "test"

    # Entry points
    if basename in _ENTRY_BASENAMES:
        return "entry"
    if package_json_main:
        main_normed = posixpath.normpath(package_json_main)
        if posixpath.normpath(path) == main_normed:
            return "entry"
    # ``if __name__`` block
    for sym in symbols:
        if sym.name == "__main__" or sym.name == "if __name__":
            return "entry"

    # Only code/notebook files can be core/helper
    if kind not in ("code", "notebook"):
        return "other"

    # Helper heuristic
    stem = posixpath.splitext(basename)[0].lower()
    if stem in _HELPER_BASENAMES:
        return "helper"
    if in_degree > 3 and out_degree <= 1:
        return "helper"

    return "core"


def _loc_from_parsed(pf: ParsedFile) -> int:
    """Estimate LOC from symbols or fall back to 0."""
    if pf.symbols:
        return max(s.end_line for s in pf.symbols)
    return 0


# ---------------------------------------------------------------------------
# Folder graph
# ---------------------------------------------------------------------------


def _build_folder_graph(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> FolderGraph:
    """Aggregate file-level graph into a folder-level view."""
    # Gather files per folder
    folder_files: dict[str, list[GraphNode]] = defaultdict(list)
    node_by_id: dict[str, GraphNode] = {}
    for n in nodes:
        folder_files[n.folder].append(n)
        node_by_id[n.id] = n

    folder_nodes: list[FolderNode] = []
    for folder, file_nodes in sorted(folder_files.items()):
        total_loc = sum(n.loc for n in file_nodes)
        roles = [n.role for n in file_nodes]
        role_counts = Counter(roles)
        folder_role = role_counts.most_common(1)[0][0] if role_counts else "other"
        entry_count = role_counts.get("entry", 0)

        summary = _folder_summary(folder, file_nodes, entry_count)

        folder_nodes.append(
            FolderNode(
                id=folder,
                label=posixpath.basename(folder) if folder != "." else ".",
                files=[n.id for n in file_nodes],
                role=folder_role,
                summary=summary,
                file_count=len(file_nodes),
                loc=total_loc,
            )
        )

    # Aggregate edges
    folder_edge_key: dict[tuple[str, str, str], int] = Counter()
    for e in edges:
        src_node = node_by_id.get(e.source)
        tgt_node = node_by_id.get(e.target)
        if not src_node or not tgt_node:
            continue
        src_folder = src_node.folder
        tgt_folder = tgt_node.folder
        if src_folder == tgt_folder:
            continue
        folder_edge_key[(src_folder, tgt_folder, e.kind)] += 1

    folder_edges = [
        FolderEdge(source=s, target=t, kind=k, count=c)
        for (s, t, k), c in sorted(folder_edge_key.items())
    ]

    return FolderGraph(nodes=folder_nodes, edges=folder_edges)


def _folder_summary(
    folder: str,
    file_nodes: list[GraphNode],
    entry_count: int,
) -> str:
    """Generate a one-line summary for a folder."""
    lang_counts: dict[str, int] = Counter()
    for n in file_nodes:
        if n.language:
            lang_counts[n.language] += 1

    total = len(file_nodes)
    if lang_counts:
        top_lang = lang_counts.most_common(1)[0][0].capitalize()
        lang_part = f"{total} {top_lang} file{'s' if total != 1 else ''}"
    else:
        lang_part = f"{total} file{'s' if total != 1 else ''}"

    label = posixpath.basename(folder) if folder != "." else "Root"
    entry_part = f" ({entry_count} entry point{'s' if entry_count != 1 else ''})" if entry_count else ""

    return f"{label} package with {lang_part}{entry_part}"


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------


def dependents_of(graph: RepoGraph, file_path: str) -> list[str]:
    """Return files that depend on *file_path* (incoming edges)."""
    return sorted({e.source for e in graph.edges if e.target == file_path})


def dependencies_of(graph: RepoGraph, file_path: str) -> list[str]:
    """Return files that *file_path* depends on (outgoing edges)."""
    return sorted({e.target for e in graph.edges if e.source == file_path})


def entry_points(graph: RepoGraph) -> list[str]:
    """Return all files with role ``entry``."""
    return sorted(n.id for n in graph.nodes if n.role == "entry")


def cycles(graph: RepoGraph) -> list[list[str]]:
    """Detect import cycles using iterative DFS.

    Returns a list of cycles, where each cycle is a list of file paths
    forming the loop.
    """
    # Build adjacency from import edges only
    adj: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        if e.kind == "import":
            adj[e.source].append(e.target)

    all_nodes = {n.id for n in graph.nodes}
    visited: set[str] = set()
    on_stack: set[str] = set()
    found_cycles: list[list[str]] = []

    for start in sorted(all_nodes):
        if start in visited:
            continue
        # Iterative DFS with path tracking
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = []

        while stack:
            node, idx = stack.pop()

            # Backtrack path to current depth
            while len(path) > len(stack):
                leaving = path.pop()
                on_stack.discard(leaving)

            if node in on_stack:
                # Found a cycle
                cycle_start = path.index(node)
                found_cycles.append(path[cycle_start:] + [node])
                continue

            if node in visited:
                continue

            path.append(node)
            on_stack.add(node)

            neighbours = adj.get(node, [])
            if idx == 0:
                visited.add(node)

            has_unvisited = False
            for neighbour in sorted(neighbours):
                if neighbour in on_stack:
                    cycle_start = path.index(neighbour)
                    found_cycles.append(path[cycle_start:] + [neighbour])
                elif neighbour not in visited:
                    stack.append((node, idx + 1))
                    stack.append((neighbour, 0))
                    has_unvisited = True
                    break

            if not has_unvisited:
                path.pop()
                on_stack.discard(node)

    return found_cycles


def most_connected(graph: RepoGraph, n: int = 10) -> list[str]:
    """Return top *n* files by ``in_degree + out_degree``."""
    ranked = sorted(
        graph.nodes,
        key=lambda nd: nd.in_degree + nd.out_degree,
        reverse=True,
    )
    return [nd.id for nd in ranked[:n]]


def transitive_dependents_count(graph: RepoGraph, file_path: str) -> int:
    """Count all transitive dependents of *file_path*."""
    # BFS over reverse edges
    reverse_adj: dict[str, set[str]] = defaultdict(set)
    for e in graph.edges:
        reverse_adj[e.target].add(e.source)

    visited: set[str] = set()
    queue = [file_path]
    while queue:
        current = queue.pop(0)
        for dep in reverse_adj.get(current, set()):
            if dep not in visited and dep != file_path:
                visited.add(dep)
                queue.append(dep)

    return len(visited)


def reading_order(graph: RepoGraph) -> list[str]:
    """Return 5-8 files as a recommended reading order.

    Algorithm: start with entry points, add their most-imported
    dependencies, add most-connected files, deduplicate, take first 8.
    """
    order: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        if path not in seen:
            seen.add(path)
            order.append(path)

    # 1. Entry points
    for ep in entry_points(graph):
        _add(ep)

    # 2. Their most-imported dependencies (sorted by in_degree desc)
    node_map = {n.id: n for n in graph.nodes}
    for ep in list(order):
        deps = dependencies_of(graph, ep)
        deps_ranked = sorted(
            deps,
            key=lambda d: node_map[d].in_degree if d in node_map else 0,
            reverse=True,
        )
        for dep in deps_ranked[:3]:
            _add(dep)

    # 3. Most-connected files
    for mc in most_connected(graph, 10):
        _add(mc)

    # Deduplicate already handled; take first 8
    result = order[:8]

    # Ensure at least 5 if possible
    if len(result) < 5:
        for n in graph.nodes:
            if len(result) >= 5:
                break
            _add(n.id)
        result = order[:8]

    return result
