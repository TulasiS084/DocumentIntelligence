"""Dataclasses for parser outputs used across all file parsers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SymbolDef:
    """A named symbol (function, class, or method) found in a source file."""

    name: str
    kind: str  # "function", "class", "method"
    start_line: int  # 1-based
    end_line: int  # 1-based


@dataclass
class ImportInfo:
    """A single import statement."""

    module: str  # raw module string
    names: list[str]  # imported names, empty for bare imports
    is_relative: bool


@dataclass
class CallInfo:
    """A function/method call expression."""

    callee: str
    line: int  # 1-based


@dataclass
class ParsedFile:
    """Unified output produced by every parser."""

    path: str  # POSIX relative
    language: str
    kind: str  # "code", "notebook", "doc", "config", "sql", "data", "test", "other"
    symbols: list[SymbolDef] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    references: list[str] = field(default_factory=list)  # string-literal paths to other files
    summary_hint: str = ""
    parse_error: str | None = None
