"""Tree-sitter based parser for Python, JavaScript, and TypeScript source files."""

from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from typing import Optional

from app.ingest.parsers.models import CallInfo, ImportInfo, ParsedFile, SymbolDef

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language loading helpers
# ---------------------------------------------------------------------------

_LANGUAGES: dict[str, object] = {}

_FILE_REF_PATTERN = re.compile(
    r"""(?:open|read_csv|read_json|read_excel|read_parquet|read_table"""
    r"""|to_csv|to_json|load|save|read_text|read_bytes|write_text"""
    r"""|write_bytes|readFile|writeFile|readFileSync|writeFileSync"""
    r"""|require)\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)

_FILE_EXTENSIONS = {
    ".csv", ".json", ".yaml", ".yml", ".toml", ".txt", ".md",
    ".sql", ".html", ".xml", ".env", ".cfg", ".ini", ".conf",
    ".png", ".jpg", ".svg", ".gif", ".pdf",
}


def _get_language(lang_key: str) -> object | None:
    """Return a cached tree-sitter Language object, or None on failure."""
    if lang_key in _LANGUAGES:
        return _LANGUAGES[lang_key]
    try:
        if lang_key == "python":
            import tree_sitter_python as tsp
            _LANGUAGES[lang_key] = tsp.language()
        elif lang_key == "javascript":
            import tree_sitter_javascript as tsjs
            _LANGUAGES[lang_key] = tsjs.language()
        elif lang_key == "typescript":
            import tree_sitter_typescript as tsts
            _LANGUAGES[lang_key] = tsts.language_typescript()
        elif lang_key == "tsx":
            import tree_sitter_typescript as tsts
            _LANGUAGES[lang_key] = tsts.language_tsx()
        else:
            return None
        return _LANGUAGES[lang_key]
    except Exception:
        logger.debug("Failed to load tree-sitter language %s", lang_key, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Extension → language key mapping
# ---------------------------------------------------------------------------

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}


# ---------------------------------------------------------------------------
# Test-file detection
# ---------------------------------------------------------------------------

_TEST_DIR_NAMES = {"tests", "__tests__", "test"}


def _is_test_file(path: str) -> bool:
    """Return True if *path* looks like a test file."""
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    stem = PurePosixPath(name).stem

    # Directory-based detection
    for part in parts[:-1]:
        if part.lower() in _TEST_DIR_NAMES:
            return True

    # Name-based detection
    if stem.startswith("test_") or stem.endswith("_test"):
        return True
    if stem.endswith(".test") or stem.endswith(".spec"):
        return True
    # Handle double-extensions like foo.test.ts
    if ".test." in name or ".spec." in name:
        return True

    return False


# ---------------------------------------------------------------------------
# Tree-sitter AST walking helpers
# ---------------------------------------------------------------------------

def _walk_tree(node: object) -> list:
    """Yield all descendant nodes via a non-recursive stack walk."""
    stack = [node]
    results: list = []
    while stack:
        current = stack.pop()
        results.append(current)
        stack.extend(reversed(current.children))
    return results


def _node_text(node: object, source_bytes: bytes) -> str:
    """Extract the UTF-8 text of a tree-sitter node."""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Python-specific extraction
# ---------------------------------------------------------------------------

def _extract_python(root_node: object, source_bytes: bytes) -> tuple[
    list[SymbolDef], list[ImportInfo], list[CallInfo], str,
]:
    """Extract symbols, imports, calls, and a summary hint from a Python AST."""
    symbols: list[SymbolDef] = []
    imports: list[ImportInfo] = []
    calls: list[CallInfo] = []
    first_docstring: str = ""

    all_nodes = _walk_tree(root_node)

    for node in all_nodes:
        ntype = node.type

        # ----- Functions & classes -----
        if ntype == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source_bytes)
                # Determine if method (parent is class body)
                kind = "function"
                parent = node.parent
                if parent and parent.type == "block":
                    grandparent = parent.parent
                    if grandparent and grandparent.type == "class_definition":
                        kind = "method"
                symbols.append(SymbolDef(
                    name=name,
                    kind=kind,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                ))

        elif ntype == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append(SymbolDef(
                    name=_node_text(name_node, source_bytes),
                    kind="class",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                ))

        # ----- Imports -----
        elif ntype == "import_statement":
            # import foo, import foo.bar
            for child in node.children:
                if child.type in ("dotted_name", "aliased_import"):
                    mod_node = child if child.type == "dotted_name" else child.child_by_field_name("name")
                    if mod_node:
                        imports.append(ImportInfo(
                            module=_node_text(mod_node, source_bytes),
                            names=[],
                            is_relative=False,
                        ))

        elif ntype == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            module_str = _node_text(module_node, source_bytes) if module_node else ""
            # Detect relative: look for leading dots
            is_relative = False
            for child in node.children:
                if child.type == "relative_import" or _node_text(child, source_bytes).startswith("."):
                    is_relative = True
                    if not module_str:
                        module_str = _node_text(child, source_bytes)
                    break
            # In some tree-sitter grammars the module is inside a relative_import node
            if not module_str:
                for child in node.children:
                    if child.type == "relative_import":
                        module_str = _node_text(child, source_bytes)
                        is_relative = True
                        break
                    elif child.type == "dotted_name":
                        module_str = _node_text(child, source_bytes)
                        break
            names: list[str] = []
            for child in node.children:
                if child.type == "dotted_name" and child != module_node:
                    names.append(_node_text(child, source_bytes))
                elif child.type == "aliased_import":
                    name_n = child.child_by_field_name("name")
                    if name_n:
                        names.append(_node_text(name_n, source_bytes))
            imports.append(ImportInfo(
                module=module_str,
                names=names,
                is_relative=is_relative,
            ))

        # ----- Calls -----
        elif ntype == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                calls.append(CallInfo(
                    callee=_node_text(func_node, source_bytes),
                    line=node.start_point[0] + 1,
                ))

        # ----- Docstring (first expression_statement > string in module body) -----
        elif ntype == "expression_statement" and not first_docstring:
            if node.parent and node.parent.type == "module":
                for child in node.children:
                    if child.type == "string":
                        raw = _node_text(child, source_bytes).strip("'\"")
                        first_docstring = raw[:200].strip()
                        break

    return symbols, imports, calls, first_docstring


# ---------------------------------------------------------------------------
# JavaScript / TypeScript extraction
# ---------------------------------------------------------------------------

def _extract_js_ts(root_node: object, source_bytes: bytes) -> tuple[
    list[SymbolDef], list[ImportInfo], list[CallInfo], str,
]:
    """Extract symbols, imports, calls, and summary hint from JS/TS AST."""
    symbols: list[SymbolDef] = []
    imports: list[ImportInfo] = []
    calls: list[CallInfo] = []
    first_comment: str = ""

    all_nodes = _walk_tree(root_node)

    for node in all_nodes:
        ntype = node.type

        # ----- Functions -----
        if ntype in ("function_declaration", "generator_function_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append(SymbolDef(
                    name=_node_text(name_node, source_bytes),
                    kind="function",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                ))

        elif ntype == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append(SymbolDef(
                    name=_node_text(name_node, source_bytes),
                    kind="class",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                ))

        elif ntype == "method_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append(SymbolDef(
                    name=_node_text(name_node, source_bytes),
                    kind="method",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                ))

        # Arrow functions assigned to variables: const foo = (...) => { ... }
        elif ntype == "lexical_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    name_n = child.child_by_field_name("name")
                    value_n = child.child_by_field_name("value")
                    if name_n and value_n and value_n.type == "arrow_function":
                        symbols.append(SymbolDef(
                            name=_node_text(name_n, source_bytes),
                            kind="function",
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                        ))

        # ----- Imports -----
        elif ntype == "import_statement":
            source_node = node.child_by_field_name("source")
            module_str = ""
            if source_node:
                module_str = _node_text(source_node, source_bytes).strip("'\"")
            names: list[str] = []
            for child in node.children:
                if child.type == "import_clause":
                    for sub in _walk_tree(child):
                        if sub.type == "identifier":
                            names.append(_node_text(sub, source_bytes))
                        elif sub.type == "import_specifier":
                            name_n = sub.child_by_field_name("name")
                            if name_n:
                                names.append(_node_text(name_n, source_bytes))
            imports.append(ImportInfo(
                module=module_str,
                names=names,
                is_relative=module_str.startswith("."),
            ))

        # ----- Call expressions -----
        elif ntype == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee_text = _node_text(func_node, source_bytes)
                # Skip deeply nested callee strings to keep data clean
                if len(callee_text) < 120:
                    calls.append(CallInfo(
                        callee=callee_text,
                        line=node.start_point[0] + 1,
                    ))

        # ----- First comment -----
        elif ntype == "comment" and not first_comment:
            raw = _node_text(node, source_bytes)
            # Strip comment markers
            raw = raw.lstrip("/").lstrip("*").strip()
            if raw:
                first_comment = raw[:200]

    return symbols, imports, calls, first_comment


# ---------------------------------------------------------------------------
# String-literal file references
# ---------------------------------------------------------------------------

def _extract_file_references(content: str, all_paths: set[str]) -> list[str]:
    """Find string literals that look like paths to known repo files."""
    refs: list[str] = []
    seen: set[str] = set()

    for match in _FILE_REF_PATTERN.finditer(content):
        candidate = match.group(1)
        # Normalise to POSIX
        candidate = candidate.replace("\\", "/")
        if candidate in all_paths and candidate not in seen:
            refs.append(candidate)
            seen.add(candidate)
            continue
        # Check if it has a file-like extension
        suffix = PurePosixPath(candidate).suffix.lower()
        if suffix in _FILE_EXTENSIONS and candidate not in seen:
            refs.append(candidate)
            seen.add(candidate)

    # Also detect any quoted string that exactly matches a known file path in all_paths
    for match in re.finditer(r"""['"]([^'"\n\r]+)['"]""", content):
        candidate = match.group(1).replace("\\", "/")
        if candidate in all_paths and candidate not in seen:
            refs.append(candidate)
            seen.add(candidate)

    return refs


# ---------------------------------------------------------------------------
# Summary hint
# ---------------------------------------------------------------------------

def _build_summary_hint(
    path: str,
    language: str,
    symbols: list[SymbolDef],
    first_doc: str,
) -> str:
    """Build a deterministic, short summary line."""
    if first_doc:
        return first_doc

    lang_label = language.capitalize()
    funcs = [s.name for s in symbols if s.kind == "function"]
    classes = [s.name for s in symbols if s.kind == "class"]

    parts: list[str] = []
    if classes:
        names = ", ".join(classes[:5])
        parts.append(f"{len(classes)} class{'es' if len(classes) != 1 else ''}: {names}")
    if funcs:
        names = ", ".join(funcs[:5])
        parts.append(f"{len(funcs)} function{'s' if len(funcs) != 1 else ''}: {names}")

    if parts:
        return f"{lang_label} file with {', '.join(parts)}"
    return f"{lang_label} file"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_code_file(
    path: str,
    language: str,
    content: str,
    all_paths: set[str],
) -> ParsedFile:
    """Parse a source file using tree-sitter and return a ParsedFile.

    Supported languages: python, javascript, typescript.
    The *path* must be a POSIX-style relative path.
    """
    import tree_sitter as ts

    ext = PurePosixPath(path).suffix.lower()
    lang_key = _EXT_TO_LANG.get(ext)
    if lang_key is None:
        return ParsedFile(
            path=path,
            language=language,
            kind="code",
            summary_hint=f"Unsupported code extension: {ext}",
            parse_error=f"No tree-sitter grammar for {ext}",
        )

    ts_language = _get_language(lang_key)
    if ts_language is None:
        return ParsedFile(
            path=path,
            language=language,
            kind="code",
            summary_hint="",
            parse_error=f"Could not load tree-sitter language: {lang_key}",
        )

    parser = ts.Parser(ts.Language(ts_language))
    source_bytes = content.encode("utf-8", errors="replace")
    tree = parser.parse(source_bytes)

    if lang_key == "python":
        symbols, imports, calls, first_doc = _extract_python(tree.root_node, source_bytes)
    else:
        symbols, imports, calls, first_doc = _extract_js_ts(tree.root_node, source_bytes)

    references = _extract_file_references(content, all_paths)

    kind = "test" if _is_test_file(path) else "code"
    summary_hint = _build_summary_hint(path, language, symbols, first_doc)

    return ParsedFile(
        path=path,
        language=language,
        kind=kind,
        symbols=symbols,
        imports=imports,
        calls=calls,
        references=references,
        summary_hint=summary_hint,
    )
