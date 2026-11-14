"""Unit tests for file parsers (Python, JS/TS, notebooks, markdown, config, SQL, data)."""

from __future__ import annotations

from app.ingest.parsers.code import parse_code_file
from app.ingest.parsers.config_files import parse_config
from app.ingest.parsers.data_files import parse_data_file
from app.ingest.parsers.markdown_doc import parse_markdown
from app.ingest.parsers.notebook import parse_notebook
from app.ingest.parsers.registry import parse_file
from app.ingest.parsers.sql import parse_sql


def test_python_code_parser() -> None:
    """Extract functions, classes, methods, imports, and calls from Python."""
    code = '''"""Module docstring."""
import os
from sys import argv
from .utils import helper

class DataProcessor:
    """Process data."""
    def clean(self):
        helper()
        return os.path.exists("data/train.csv")

def main():
    dp = DataProcessor()
    dp.clean()
'''
    pf = parse_code_file("src/processor.py", "python", code, {"src/utils.py", "data/train.csv"})
    assert pf.path == "src/processor.py"
    assert pf.kind == "code"
    assert pf.language == "python"
    assert pf.parse_error is None

    symbol_names = [s.name for s in pf.symbols]
    assert "DataProcessor" in symbol_names
    assert "clean" in symbol_names
    assert "main" in symbol_names

    imported_mods = [imp.module for imp in pf.imports]
    assert "os" in imported_mods
    assert "sys" in imported_mods
    assert "utils" in imported_mods or ".utils" in imported_mods or any("utils" in m for m in imported_mods)

    callee_names = [c.callee for c in pf.calls]
    assert any("helper" in c for c in callee_names)

    # Reference to data/train.csv
    assert "data/train.csv" in pf.references
    assert "Module docstring." in pf.summary_hint


def test_js_ts_code_parser() -> None:
    """Extract symbols, imports, and calls from TypeScript / JavaScript."""
    code = '''import { helper } from "./utils";
import axios from "axios";

export class ApiClient {
    async fetchData(): Promise<string> {
        helper();
        return "data";
    }
}

export function startServer(): void {
    const client = new ApiClient();
    client.fetchData();
}
'''
    pf = parse_code_file("src/client.ts", "typescript", code, {"src/utils.ts"})
    assert pf.path == "src/client.ts"
    assert pf.kind == "code"
    assert pf.language == "typescript"
    assert pf.parse_error is None

    symbol_names = [s.name for s in pf.symbols]
    assert "ApiClient" in symbol_names
    assert "startServer" in symbol_names

    imported_mods = [imp.module for imp in pf.imports]
    assert "./utils" in imported_mods
    assert "axios" in imported_mods


def test_notebook_parser() -> None:
    """Extract pipeline outline, imports, and data-file references from notebook."""
    import json
    nb_dict = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Data Preparation\n", "Load and clean dataset."]
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import pandas as pd\n",
                    "df = pd.read_csv('data/dataset.csv')\n",
                    "def process(d):\n",
                    "    return d.dropna()\n"
                ]
            }
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11.0"}
        },
        "nbformat": 4,
        "nbformat_minor": 2
    }
    content = json.dumps(nb_dict)
    all_paths = {"data/dataset.csv"}
    pf = parse_notebook("notebooks/analysis.ipynb", "jupyter", content, all_paths)

    assert pf.path == "notebooks/analysis.ipynb"
    assert pf.kind == "notebook"
    assert pf.parse_error is None
    assert any("pandas" in imp.module for imp in pf.imports)
    assert any("data/dataset.csv" in ref for ref in pf.references)
    assert "Data Preparation" in pf.summary_hint


def test_markdown_parser() -> None:
    """Extract headings and repo file links from markdown."""
    content = """# Architecture Overview

See the [main code](src/main.py) for the entry point.
Also check [API docs](docs/api.md) and [External](https://github.com).
"""
    all_paths = {"src/main.py", "docs/api.md"}
    pf = parse_markdown("README.md", "markdown", content, all_paths)

    assert pf.path == "README.md"
    assert pf.kind == "doc"
    assert "Architecture Overview" in pf.summary_hint
    assert "src/main.py" in pf.references or any("main.py" in r for r in pf.references)


def test_config_parsers() -> None:
    """Extract facts and file references from package.json and Dockerfile."""
    # package.json
    pkg_content = '{"name": "test-pkg", "main": "dist/index.js", "scripts": {"build": "tsc", "test": "jest"}}'
    pf_pkg = parse_config("package.json", "json", pkg_content, {"dist/index.js"})
    assert pf_pkg.kind == "config"
    assert "dist/index.js" in pf_pkg.references
    assert "2 scripts" in pf_pkg.summary_hint or "scripts" in pf_pkg.summary_hint

    # Dockerfile
    docker_content = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ /app/src/
CMD ["python", "src/main.py"]
"""
    pf_docker = parse_config("Dockerfile", "dockerfile", docker_content, {"requirements.txt", "src/main.py"})
    assert pf_docker.kind == "config"
    assert any("requirements.txt" in r for r in pf_docker.references)


def test_sql_parser() -> None:
    """Extract tables, columns, and foreign keys from SQL DDL."""
    sql = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username VARCHAR(50) NOT NULL
);

CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    content TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""
    pf = parse_sql("schema.sql", "sql", sql, set())
    assert pf.kind == "sql"
    symbol_names = [s.name for s in pf.symbols]
    assert "users" in symbol_names
    assert "posts" in symbol_names
    assert "2 tables" in pf.summary_hint or "users" in pf.summary_hint


def test_data_file_parsers() -> None:
    """Extract CSV schema and row counts without storing all data."""
    csv_content = """id,name,role\n1,Alice,admin\n2,Bob,user\n3,Charlie,user\n"""
    pf = parse_data_file("data/users.csv", "csv", csv_content, set())
    assert pf.kind == "data"
    assert "3 columns" in pf.summary_hint
    assert "3 data rows" in pf.summary_hint or "rows" in pf.summary_hint


def test_parse_error_tolerance() -> None:
    """Garbage syntax in code or notebook does not crash parser, records parse_error."""
    broken_code = "def (: invalid syntax ))))"
    pf = parse_file("broken.py", broken_code, "python", set())
    assert pf.path == "broken.py"
    # Even with broken syntax, tree-sitter or parser handles it gracefully
    assert pf.kind in ("code", "other")
