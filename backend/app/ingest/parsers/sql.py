"""Parse SQL files: extract tables, columns, and relationships."""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.ingest.parsers.models import ParsedFile, SymbolDef

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for SQL DDL
# ---------------------------------------------------------------------------

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?(\w+)[`\"\]]?\s*\(",
    re.IGNORECASE,
)

_COLUMN_DEF = re.compile(
    r"^\s+[`\"\[]?(\w+)[`\"\]]?\s+([\w()]+)",
    re.MULTILINE,
)

_FOREIGN_KEY = re.compile(
    r"FOREIGN\s+KEY\s*\([`\"\[]?(\w+)[`\"\]]?\)\s*REFERENCES\s+[`\"\[]?(\w+)[`\"\]]?\s*\([`\"\[]?(\w+)[`\"\]]?\)",
    re.IGNORECASE,
)

_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+[`\"\[]?(\w+)[`\"\]]?",
    re.IGNORECASE,
)

_CREATE_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?(\w+)[`\"\]]?\s+ON\s+[`\"\[]?(\w+)[`\"\]]?",
    re.IGNORECASE,
)

# SQL keywords that should not be treated as column names
_SQL_KEYWORDS = {
    "primary", "key", "not", "null", "default", "unique", "check",
    "constraint", "foreign", "references", "index", "create", "table",
    "alter", "drop", "insert", "update", "delete", "select", "from",
    "where", "and", "or", "on", "if", "exists", "cascade",
}


def parse_sql(
    path: str,
    language: str,
    content: str,
    all_paths: set[str],
) -> ParsedFile:
    """Parse a SQL file and return a ParsedFile.

    Extracts CREATE TABLE statements as symbols, plus column
    information and foreign-key relationships in the summary.
    """
    symbols: list[SymbolDef] = []
    tables: dict[str, list[str]] = {}  # table_name -> [columns]
    relationships: list[str] = []

    # --- CREATE TABLE ---
    for match in _CREATE_TABLE.finditer(content):
        table_name = match.group(1)
        start_pos = match.start()
        start_line = content[:start_pos].count("\n") + 1

        # Find the closing paren for the table body
        paren_depth = 0
        end_pos = match.end()
        for i in range(match.end(), len(content)):
            if content[i] == "(":
                paren_depth += 1
            elif content[i] == ")":
                if paren_depth == 0:
                    end_pos = i
                    break
                paren_depth -= 1
        end_line = content[:end_pos].count("\n") + 1

        symbols.append(SymbolDef(
            name=table_name,
            kind="class",  # tables are analogous to classes
            start_line=start_line,
            end_line=end_line,
        ))

        # Extract columns from the table body
        body = content[match.end():end_pos]
        columns: list[str] = []
        for col_match in _COLUMN_DEF.finditer(body):
            col_name = col_match.group(1).lower()
            if col_name not in _SQL_KEYWORDS:
                columns.append(col_match.group(1))
        tables[table_name] = columns

        # Extract inline FOREIGN KEY references
        for fk_match in _FOREIGN_KEY.finditer(body):
            fk_col = fk_match.group(1)
            ref_table = fk_match.group(2)
            ref_col = fk_match.group(3)
            relationships.append(f"{table_name}.{fk_col} -> {ref_table}.{ref_col}")

    # --- Standalone FOREIGN KEY via ALTER TABLE ---
    for alter_match in _ALTER_TABLE.finditer(content):
        alter_table = alter_match.group(1)
        # Look for FOREIGN KEY after this ALTER TABLE
        rest = content[alter_match.end():]
        fk_match = _FOREIGN_KEY.search(rest)
        if fk_match:
            fk_col = fk_match.group(1)
            ref_table = fk_match.group(2)
            ref_col = fk_match.group(3)
            relationships.append(f"{alter_table}.{fk_col} -> {ref_table}.{ref_col}")

    # --- Build summary ---
    parts: list[str] = []
    if tables:
        parts.append(f"{len(tables)} table{'s' if len(tables) != 1 else ''}: {', '.join(list(tables.keys())[:6])}")
    if relationships:
        parts.append(f"{len(relationships)} relationship{'s' if len(relationships) != 1 else ''}")
    summary_hint = "SQL file with " + "; ".join(parts) if parts else "SQL file"

    return ParsedFile(
        path=path,
        language=language or "sql",
        kind="sql",
        symbols=symbols,
        summary_hint=summary_hint,
    )
