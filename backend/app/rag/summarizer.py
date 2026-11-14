"""Layered repository summarizer (file, folder, project levels) with LLM and deterministic fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import save_repo_summary
from app.llm import LLMUnavailableError, generate
from app.models import RepoFile, RepoSummary

logger = logging.getLogger(__name__)

# Entry point patterns to prioritize for LLM file summarization
_ENTRY_PATTERNS = re.compile(
    r"(main|index|app|server|cli|init|manage|setup|config|router|routes)\.(py|ts|js|jsx|tsx|go|rs)$",
    re.IGNORECASE,
)


def _clean_json_response(raw: str) -> str:
    """Extract JSON object or array from markdown code fences or raw text."""
    trimmed = raw.strip()
    if trimmed.startswith("```"):
        lines = trimmed.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        trimmed = "\n".join(lines).strip()
    return trimmed


def _deterministic_file_summary(file_info: dict[str, Any]) -> str:
    """Generate a structured deterministic summary from parse metadata."""
    path = file_info.get("path", "")
    lang = file_info.get("language") or "unknown"
    loc = file_info.get("loc", 0)
    symbols = file_info.get("symbols", [])
    imports = file_info.get("imports", [])

    sym_names = [s.get("name") for s in symbols if isinstance(s, dict) and s.get("name")][:5]
    imp_modules = [
        imp.get("module") for imp in imports if isinstance(imp, dict) and imp.get("module")
    ][:5]

    sym_desc = f" Defines {', '.join(sym_names)}." if sym_names else ""
    imp_desc = f" Imports from {', '.join(imp_modules)}." if imp_modules else ""
    return f"{path} ({lang}, {loc} lines).{sym_desc}{imp_desc}".strip()


def _deterministic_project_summary(
    files: list[RepoFile],
    stats: dict[str, Any],
    readme_content: Optional[str] = None,
) -> dict[str, Any]:
    """Build a deterministic project overview without an LLM."""
    languages = list(stats.get("languages", {}).keys())
    total_loc = stats.get("total_loc", 0)
    total_files = stats.get("total_files", len(files))

    # Infer overview from README if available
    overview = f"Repository containing {total_files} files across {total_loc} lines of code."
    if readme_content:
        # First non-empty paragraph or header
        lines = [line.strip() for line in readme_content.splitlines() if line.strip()]
        for line in lines:
            if not line.startswith("#") and len(line) > 20:
                overview = line[:300]
                break

    # Infer key files
    key_files = []
    for f in files:
        basename = f.path.split("/")[-1].lower()
        if basename in (
            "readme.md",
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "cargo.toml",
            "go.mod",
            "dockerfile",
            "main.py",
            "index.ts",
            "index.js",
            "app.py",
        ):
            key_files.append(f.path)
    if not key_files:
        key_files = [f.path for f in files[:5]]

    # Infer folder guide
    folder_guide: dict[str, str] = {}
    folders = set()
    for f in files:
        parts = f.path.split("/")
        if len(parts) > 1:
            folders.add(parts[0])
    for folder in sorted(folders):
        folder_guide[folder] = f"Source directory for {folder} modules."

    # Infer how to run
    how_to_run = "Inspect README.md and dependency configuration files for execution instructions."
    filenames = {f.path.split("/")[-1].lower() for f in files}
    if "package.json" in filenames:
        how_to_run = "npm install && npm start (or npm run dev)"
    elif "requirements.txt" in filenames or "pyproject.toml" in filenames:
        how_to_run = "pip install -r requirements.txt && python main.py"
    elif "cargo.toml" in filenames:
        how_to_run = "cargo build && cargo run"
    elif "go.mod" in filenames:
        how_to_run = "go run ."

    return {
        "overview": overview,
        "stack": languages if languages else ["Source Code"],
        "how_to_run": how_to_run,
        "folder_guide": folder_guide,
        "key_files": key_files[:8],
    }


def summarize_file(
    repo_id: str,
    file_record: RepoFile,
    file_info: dict[str, Any],
    allow_llm: bool = True,
) -> tuple[str, str]:
    """Summarize a single file.

    Returns:
        tuple of (summary_text, source: "llm" | "deterministic")
    """
    if not allow_llm or not file_record.content:
        return _deterministic_file_summary(file_info), "deterministic"

    prompt = (
        f"Analyze this code file from repository {repo_id}:\n"
        f"File Path: {file_record.path}\n"
        f"Language: {file_record.language}\n\n"
        f"Content:\n{file_record.content[:2000]}\n\n"
        f"Provide a concise 1-2 sentence description explaining the file's primary purpose "
        f"and key responsibilities. Do not include markdown headers."
    )
    system = "You are an expert software architect analyzing code repositories."

    try:
        summary_text = generate(prompt, system=system, temperature=0.1, max_tokens=150)
        return summary_text.strip(), "llm"
    except (LLMUnavailableError, Exception) as e:
        logger.debug("LLM file summarization fallback for %s: %s", file_record.path, e)
        return _deterministic_file_summary(file_info), "deterministic"


def summarize_project(
    repo_id: str,
    files: list[RepoFile],
    stats: dict[str, Any],
    file_summaries: dict[str, str],
    readme_content: Optional[str] = None,
) -> tuple[dict[str, Any], str]:
    """Generate high-level project summary with LLM or fallback.

    Returns:
        tuple of (project_dict, source: "llm" | "deterministic")
    """
    settings = get_settings()
    summary_snippets = "\n".join(
        [f"- {path}: {desc}" for path, desc in list(file_summaries.items())[:15]]
    )

    prompt = (
        f"Summarize the following software repository.\n\n"
        f"Languages: {list(stats.get('languages', {}).keys())}\n"
        f"Total LOC: {stats.get('total_loc', 0)}\n"
        f"Sample File Summaries:\n{summary_snippets}\n\n"
    )
    if readme_content:
        prompt += f"README Snippet:\n{readme_content[:1500]}\n\n"

    prompt += (
        "Respond strictly with valid JSON having the exact keys:\n"
        "{\n"
        '  "overview": "A clear 2-4 sentence executive summary of the repository\'s purpose",\n'
        '  "stack": ["Technology1", "Technology2"],\n'
        '  "how_to_run": "Concise step-by-step instructions to run/test the project",\n'
        '  "folder_guide": {"folder_name": "Description of what is in this folder"},\n'
        '  "key_files": ["important/file1.py", "important/file2.js"]\n'
        "}\n"
        "Do not wrap in markdown or backticks."
    )

    system = "You are an expert technical lead and repository auditor. Output only valid JSON."

    try:
        raw_res = generate(prompt, system=system, temperature=0.1, max_tokens=600)
        cleaned = _clean_json_response(raw_res)
        parsed = json.loads(cleaned)
        # Validate expected keys
        if (
            isinstance(parsed, dict)
            and "overview" in parsed
            and "stack" in parsed
            and "how_to_run" in parsed
        ):
            return parsed, "llm"
        logger.warning("LLM returned incomplete JSON keys, retrying fallback")
    except Exception as e:
        logger.info("Project LLM summary unavailable (%s), using deterministic fallback", e)

    return _deterministic_project_summary(files, stats, readme_content), "deterministic"


def summarize_repository(
    session: Session,
    repo_id: str,
    files: list[RepoFile],
    parse_results: dict[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Perform full layered summarization (files, folders, project) and persist."""
    settings = get_settings()
    max_llm_calls = settings.max_summary_calls

    # Find README content if any
    readme_content = None
    for f in files:
        if f.path.lower() in ("readme.md", "readme.rst", "readme.txt", "readme"):
            readme_content = f.content
            break

    # Prioritize files for LLM calls
    # 1. README
    # 2. Main entry files matching _ENTRY_PATTERNS
    # 3. Rest
    file_map = {f.path: f for f in files}
    prioritized_paths: list[str] = []

    for f in files:
        if _ENTRY_PATTERNS.search(f.path):
            prioritized_paths.append(f.path)

    for f in files:
        if f.path not in prioritized_paths:
            prioritized_paths.append(f.path)

    llm_calls_made = 0
    llm_available = True
    file_summaries: dict[str, str] = {}

    for path in prioritized_paths:
        file_rec = file_map[path]
        file_info = parse_results.get(path, {})
        allow_llm = llm_available and (llm_calls_made < max_llm_calls)

        summary_text, source = summarize_file(repo_id, file_rec, file_info, allow_llm=allow_llm)
        if source == "llm":
            llm_calls_made += 1
        elif allow_llm and source == "deterministic":
            # If LLM failed or API key was missing, avoid repeating failing calls for subsequent files
            llm_available = False

        file_summaries[path] = summary_text
        # Save file summary
        save_repo_summary(
            session,
            RepoSummary(
                repo_id=repo_id,
                level="file",
                path=path,
                text=summary_text,
                source=source,
            ),
        )

    # Folder-level summaries
    folder_files: dict[str, list[str]] = {}
    for f in files:
        parts = f.path.split("/")
        if len(parts) > 1:
            folder = "/".join(parts[:-1])
            folder_files.setdefault(folder, []).append(f.path)

    for folder, paths in folder_files.items():
        sample_descs = [f"{p.split('/')[-1]}: {file_summaries.get(p, '')}" for p in paths[:4]]
        folder_text = f"Folder '{folder}' contains {len(paths)} files. " + " ".join(sample_descs)
        save_repo_summary(
            session,
            RepoSummary(
                repo_id=repo_id,
                level="folder",
                path=folder,
                text=folder_text,
                source="deterministic",
            ),
        )

    # Project-level summary
    project_dict, proj_source = summarize_project(
        repo_id, files, stats, file_summaries, readme_content
    )
    save_repo_summary(
        session,
        RepoSummary(
            repo_id=repo_id,
            level="project",
            path="",
            text=json.dumps(project_dict),
            source=proj_source,
        ),
    )

    logger.info(
        "Layered summarization complete for repo %s (LLM calls: %d, files: %d)",
        repo_id,
        llm_calls_made,
        len(files),
    )
    return project_dict
