# document intelligence system ('Document analysis and Code-Based Visual Analyzer for GitHub Repos')

upload the documents and then analyse it and ask any related questions for anything may be for exam preparation or for any document analysis.

Paste a public GitHub repository URL. The app shallow-clones it into an isolated temporary directory, scans the working tree, stores text file contents in SQLite, parses dependencies with Tree-sitter & static readers (never executing or importing anything from the clone), builds a file-connection graph, and visualizes it with an interactive layered diagram, file tree, and code viewer.

This repository implements **Step 1 & Step 2**:
- **Step 1**: URL validation, safe shallow clone (depth 1), scan limits, SQLite snapshot, Server-Sent Events for status, and React file tree.
- **Step 2**: Multi-language parsers (`code.py` using Tree-sitter for Python/JS/TS, `notebook.py` via `nbformat`, `markdown_doc.py`, `config_files.py`, `sql.py`, `data_files.py`), deterministic summaries, `graph/builder.py` (file & folder dependency graph, role detection, cycle detection, reading order), REST endpoints, React Flow interactive diagram with expand-in-place folders and code viewer.

## Layout

- `backend/app/ingest/` — Safe clone, file scanner, pipeline, and parsers (`parsers/code.py`, `notebook.py`, `markdown_doc.py`, `config_files.py`, `sql.py`, `data_files.py`, `registry.py`)
- `backend/app/graph/` — Deterministic dependency graph builder, roles, cycle detection, folder aggregation (`graph/builder.py`)
- `backend/app/models.py` — SQLAlchemy models (`Repo`, `RepoFile`) and Pydantic schemas
- `backend/app/main.py` — FastAPI application & API endpoints
- `frontend/src/components/` — `DependencyGraph.tsx` (React Flow diagram), `CodeViewer.tsx` (syntax highlighter), `FileTree.tsx`, `ProgressStepper.tsx`, `UrlForm.tsx`

## Prerequisites

- Python 3.11 or 3.12
- Node.js 20+
- Git on `PATH`

## Running Backend

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Running Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

## Running Tests

All 62 unit and integration tests run without network access and with mocked git cloning:

```bash
cd backend
pytest
```

## Security & Architectural Guarantees

- **No LLM in structural parsing**: All dependencies, roles, summaries, and graph connections are computed deterministically by code.
- **Safe Sandbox**: Shallow clone (`depth=1`), 60s timeout, 300 MB working-tree cap.
- **Zero Execution**: Files are parsed statically via tree-sitter AST and static text readers; target repositories are never executed, imported, or installed.
- **Fault-Tolerant Pipeline**: Syntax errors in individual files do not fail the pipeline; errors are recorded on the file node and the pipeline continues.
- **Auto-Cleanup**: Cloned working directories are always deleted in a `finally` block before completion.
- **POSIX Paths**: All paths are stored and queried using POSIX-style relative paths (`/`) even on Windows.
