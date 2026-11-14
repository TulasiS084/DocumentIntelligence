"""Parse data files: CSV and JSON."""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any, Optional

from app.ingest.parsers.models import ParsedFile

logger = logging.getLogger(__name__)

# Maximum rows to sample for CSV preview
_MAX_SAMPLE_ROWS = 5


def _parse_csv(path: str, language: str, content: str) -> ParsedFile:
    """Parse a CSV file: extract schema, column names, row count, and sample rows."""
    try:
        # Sniff the dialect
        sample = content[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel  # type: ignore[assignment]

        reader = csv.reader(io.StringIO(content), dialect)
        rows = list(reader)

        if not rows:
            return ParsedFile(
                path=path,
                language=language or "csv",
                kind="data",
                summary_hint="Empty CSV file",
            )

        # First row as headers
        headers = rows[0]
        data_rows = rows[1:]
        row_count = len(data_rows)

        # Sample first N rows
        sample_rows = data_rows[:_MAX_SAMPLE_ROWS]

        summary_parts = [
            f"CSV file with {len(headers)} columns, {row_count} data rows",
        ]
        if headers:
            col_list = ", ".join(headers[:8])
            if len(headers) > 8:
                col_list += f" (+{len(headers) - 8} more)"
            summary_parts.append(f"columns: {col_list}")

        return ParsedFile(
            path=path,
            language=language or "csv",
            kind="data",
            summary_hint="; ".join(summary_parts),
        )

    except Exception as exc:
        logger.warning("Failed to parse CSV %s: %s", path, exc)
        return ParsedFile(
            path=path,
            language=language or "csv",
            kind="data",
            summary_hint="CSV file (parse error)",
            parse_error=str(exc),
        )


def _infer_json_schema(obj: Any, max_depth: int = 3) -> str:
    """Return a short schema description for a JSON value."""
    if isinstance(obj, dict):
        keys = list(obj.keys())
        keys_str = ", ".join(keys[:8])
        if len(keys) > 8:
            keys_str += f" (+{len(keys) - 8} more)"
        return f"object with keys: {keys_str}"
    elif isinstance(obj, list):
        if not obj:
            return "empty array"
        first = obj[0]
        if isinstance(first, dict):
            keys = list(first.keys())
            keys_str = ", ".join(keys[:8])
            if len(keys) > 8:
                keys_str += f" (+{len(keys) - 8} more)"
            return f"array of {len(obj)} objects with keys: {keys_str}"
        return f"array of {len(obj)} {type(first).__name__} values"
    else:
        return type(obj).__name__


def _parse_json_data(path: str, language: str, content: str) -> ParsedFile:
    """Parse a JSON data file: detect structure and extract schema."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse JSON %s: %s", path, exc)
        return ParsedFile(
            path=path,
            language=language or "json",
            kind="data",
            summary_hint="JSON file (parse error)",
            parse_error=str(exc),
        )

    schema_desc = _infer_json_schema(data)
    summary_hint = f"JSON data file: {schema_desc}"

    return ParsedFile(
        path=path,
        language=language or "json",
        kind="data",
        summary_hint=summary_hint,
    )


def parse_data_file(
    path: str,
    language: str,
    content: str,
    all_paths: set[str],
) -> ParsedFile:
    """Parse a data file (CSV or JSON) and return a ParsedFile.

    For CSV: extracts column names, row count, and sample rows.
    For JSON: detects structure (array of objects vs object) and extracts keys.
    Never stores the entire dataset.
    """
    lower_path = path.lower()

    if lower_path.endswith(".csv"):
        return _parse_csv(path, language, content)
    elif lower_path.endswith(".json"):
        return _parse_json_data(path, language, content)
    else:
        return ParsedFile(
            path=path,
            language=language or "data",
            kind="data",
            summary_hint=f"Data file: {path}",
        )
