# Repo Analyzer

Paste a public GitHub repository URL. The app shallow-clones it, scans the working tree in process (never executing or installing anything from the clone), stores a file tree, then deletes the clone.

This repository currently implements **Step 1 only**: URL validation, safe clone, scan limits, SQLite snapshot, Server-Sent Events for status, and a React file tree. Parsers, RAG, chat, and diagrams are not included yet.

## Layout

- `backend/` — FastAPI, GitPython clone, scanner, SQLite
- `frontend/` — Vite + React + TypeScript + Tailwind
- `backend/app/graph`, `rag`, `agent` — empty placeholders for later steps

## Prerequisites

- Python 3.11
- Node.js 20+
- Git on `PATH`

## Backend

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
copy ..\.env.example .env   # optional; defaults are safe
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend

```bash
cd frontend
npm install
copy .env.example .env      # or set VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

Open http://localhost:5173

## Tests

```bash
cd backend
python -m pytest
```

Git clone is mocked in tests; a live GitHub clone is not required for CI.

## Security limits (Step 1)

- Only `https://github.com/<owner>/<repo>` (optional `.git` suffix)
- Shallow clone (`depth=1`), 60s timeout, 300 MB working-tree cap
- Skip ignored folders, binaries, files over 1 MB, and files after 2000 analyzed
- Temporary clone is always deleted after scan
- No secrets in source; copy `.env.example` locally
