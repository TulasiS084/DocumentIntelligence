"""Parse configuration files: package.json, requirements.txt, pyproject.toml,
Dockerfile, docker-compose.yml, CI workflows, .env.example, Makefile."""

from __future__ import annotations

import json
import logging
import re
from pathlib import PurePosixPath
from typing import Any, Optional

from app.ingest.parsers.models import ParsedFile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: find file-path-like strings in a mapping
# ---------------------------------------------------------------------------

def _extract_paths_from_value(value: Any) -> list[str]:
    """Recursively extract string values that look like file paths."""
    results: list[str] = []
    if isinstance(value, str):
        # Simple heuristic: contains a slash or dot-extension
        cleaned = value.strip()
        if "/" in cleaned or (
            "." in cleaned
            and not cleaned.startswith("http")
            and not cleaned.startswith("@")
            and len(cleaned) < 256
        ):
            results.append(cleaned.replace("\\", "/"))
    elif isinstance(value, dict):
        for v in value.values():
            results.extend(_extract_paths_from_value(v))
    elif isinstance(value, list):
        for item in value:
            results.extend(_extract_paths_from_value(item))
    return results


def _filter_refs(candidates: list[str], all_paths: set[str]) -> list[str]:
    """Keep only candidates that exist in the repo."""
    seen: set[str] = set()
    refs: list[str] = []
    for c in candidates:
        c = c.replace("\\", "/")
        if c in all_paths and c not in seen:
            refs.append(c)
            seen.add(c)
    return refs


# ---------------------------------------------------------------------------
# Individual config parsers
# ---------------------------------------------------------------------------

def _parse_package_json(content: str, all_paths: set[str]) -> tuple[str, list[str]]:
    """Parse package.json; return (summary_hint, references)."""
    data = json.loads(content)
    facts: list[str] = []
    ref_candidates: list[str] = []

    name = data.get("name", "")
    if name:
        facts.append(f"name={name}")

    main = data.get("main")
    if main:
        facts.append(f"main={main}")
        ref_candidates.append(main)

    scripts = data.get("scripts", {})
    if scripts:
        facts.append(f"{len(scripts)} npm script{'s' if len(scripts) != 1 else ''}")

    bin_field = data.get("bin")
    if isinstance(bin_field, dict):
        ref_candidates.extend(bin_field.values())
    elif isinstance(bin_field, str):
        ref_candidates.append(bin_field)

    deps = data.get("dependencies", {})
    dev_deps = data.get("devDependencies", {})
    if deps:
        facts.append(f"{len(deps)} dependencies")
    if dev_deps:
        facts.append(f"{len(dev_deps)} devDependencies")

    summary = "Config file: " + ", ".join(facts) if facts else "Config file: package.json"
    return summary, _filter_refs(ref_candidates, all_paths)


def _parse_requirements_txt(content: str, all_paths: set[str]) -> tuple[str, list[str]]:
    """Parse requirements.txt; return (summary_hint, references)."""
    lines = [
        ln.strip() for ln in content.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    # Look for -r references to other requirement files
    ref_candidates: list[str] = []
    pkgs = 0
    for ln in lines:
        if ln.startswith("-r ") or ln.startswith("--requirement "):
            ref_file = ln.split(None, 1)[1].strip()
            ref_candidates.append(ref_file)
        elif not ln.startswith("-"):
            pkgs += 1

    summary = f"Config file: {pkgs} Python dependencies"
    return summary, _filter_refs(ref_candidates, all_paths)


def _parse_pyproject_toml(content: str, all_paths: set[str]) -> tuple[str, list[str]]:
    """Parse pyproject.toml; return (summary_hint, references)."""
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(content)
    facts: list[str] = []
    ref_candidates: list[str] = []

    project = data.get("project", {})
    name = project.get("name", "")
    if name:
        facts.append(f"name={name}")

    deps = project.get("dependencies", [])
    if deps:
        facts.append(f"{len(deps)} dependencies")

    # Optional dependencies
    opt_deps = project.get("optional-dependencies", {})
    for group, items in opt_deps.items():
        facts.append(f"{len(items)} {group} deps")

    # Entry points / scripts
    scripts = project.get("scripts", {})
    if scripts:
        facts.append(f"{len(scripts)} entry point{'s' if len(scripts) != 1 else ''}")
        ref_candidates.extend(_extract_paths_from_value(scripts))

    summary = "Config file: " + ", ".join(facts) if facts else "Config file: pyproject.toml"
    return summary, _filter_refs(ref_candidates, all_paths)


def _parse_dockerfile(content: str, all_paths: set[str]) -> tuple[str, list[str]]:
    """Parse Dockerfile; return (summary_hint, references)."""
    ref_candidates: list[str] = []
    directives: dict[str, int] = {}

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Get instruction keyword
        parts = stripped.split(None, 1)
        instruction = parts[0].upper()

        if instruction in ("COPY", "ADD") and len(parts) > 1:
            directives[instruction] = directives.get(instruction, 0) + 1
            # Extract source paths (everything except last arg)
            args = parts[1].split()
            for arg in args[:-1]:
                if not arg.startswith("--"):
                    ref_candidates.append(arg)

        elif instruction in ("CMD", "ENTRYPOINT"):
            directives[instruction] = directives.get(instruction, 0) + 1

    facts = [f"{count} {instr}" for instr, count in sorted(directives.items())]
    summary = "Config file: Dockerfile with " + ", ".join(facts) if facts else "Config file: Dockerfile"
    return summary, _filter_refs(ref_candidates, all_paths)


def _parse_docker_compose(content: str, all_paths: set[str]) -> tuple[str, list[str]]:
    """Parse docker-compose.yml; return (summary_hint, references)."""
    import yaml

    data = yaml.safe_load(content) or {}
    ref_candidates: list[str] = []

    services = data.get("services", {})
    n_services = len(services)
    ports_total = 0

    for svc_name, svc_def in services.items():
        if not isinstance(svc_def, dict):
            continue
        build = svc_def.get("build")
        if isinstance(build, str):
            ref_candidates.append(build)
        elif isinstance(build, dict):
            ctx = build.get("context")
            if isinstance(ctx, str):
                ref_candidates.append(ctx)
            dockerfile = build.get("dockerfile")
            if isinstance(dockerfile, str):
                ref_candidates.append(dockerfile)
        volumes = svc_def.get("volumes", [])
        for vol in volumes:
            if isinstance(vol, str) and ":" in vol:
                host_part = vol.split(":")[0]
                ref_candidates.append(host_part)
        ports = svc_def.get("ports", [])
        ports_total += len(ports)

    facts = [f"{n_services} service{'s' if n_services != 1 else ''}"]
    if ports_total:
        facts.append(f"{ports_total} port mapping{'s' if ports_total != 1 else ''}")
    summary = "Config file: docker-compose with " + ", ".join(facts)
    return summary, _filter_refs(ref_candidates, all_paths)


def _parse_yaml_generic(
    content: str,
    path: str,
    all_paths: set[str],
) -> tuple[str, list[str]]:
    """Parse generic YAML / CI workflow files; return (summary_hint, references)."""
    import yaml

    data = yaml.safe_load(content) or {}
    ref_candidates: list[str] = []

    # Detect GitHub Actions workflow
    is_ci = ".github/workflows/" in path or ".gitlab-ci" in path
    if is_ci and isinstance(data, dict):
        workflow_name = data.get("name", PurePosixPath(path).stem)
        jobs = data.get("jobs", {})
        summary = f"CI workflow: {workflow_name}, {len(jobs)} job{'s' if len(jobs) != 1 else ''}"
    else:
        keys = list(data.keys()) if isinstance(data, dict) else []
        summary = f"Config file: YAML with keys {', '.join(keys[:6])}" if keys else "Config file: YAML"

    ref_candidates.extend(_extract_paths_from_value(data))
    return summary, _filter_refs(ref_candidates, all_paths)


def _parse_env_example(content: str, all_paths: set[str]) -> tuple[str, list[str]]:
    """Parse .env.example; return (summary_hint, references)."""
    keys: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys.append(key)
    summary = f"Config file: {len(keys)} environment variable{'s' if len(keys) != 1 else ''}"
    return summary, []


def _parse_makefile(content: str, all_paths: set[str]) -> tuple[str, list[str]]:
    """Parse Makefile; return (summary_hint, references)."""
    targets: list[str] = []
    ref_candidates: list[str] = []

    for line in content.splitlines():
        # Target lines: "target: dependencies"
        match = re.match(r"^([a-zA-Z_][\w.-]*)\s*:", line)
        if match:
            targets.append(match.group(1))

    summary = f"Config file: Makefile with {len(targets)} target{'s' if len(targets) != 1 else ''}"
    if targets:
        summary += f": {', '.join(targets[:6])}"
    return summary, _filter_refs(ref_candidates, all_paths)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Map of exact filenames to parsers
_FILENAME_PARSERS: dict[str, Any] = {
    "package.json": _parse_package_json,
    "requirements.txt": _parse_requirements_txt,
    "pyproject.toml": _parse_pyproject_toml,
    "makefile": _parse_makefile,
}

# Patterns for filename matching
_DOCKERFILE_PATTERN = re.compile(r"^dockerfile(?:\..+)?$", re.IGNORECASE)
_DOCKER_COMPOSE_PATTERN = re.compile(
    r"^(?:docker-compose|compose)(?:\..+)?\.ya?ml$", re.IGNORECASE
)
_ENV_PATTERN = re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE)


def parse_config(
    path: str,
    language: str,
    content: str,
    all_paths: set[str],
) -> ParsedFile:
    """Parse a configuration file and return a ParsedFile.

    Dispatches to specialised sub-parsers based on filename. Falls
    back to generic YAML parsing for unrecognised .yml/.yaml files.
    """
    filename = PurePosixPath(path).name.lower()

    summary_hint = ""
    references: list[str] = []

    try:
        if filename in _FILENAME_PARSERS:
            parser_fn = _FILENAME_PARSERS[filename]
            summary_hint, references = parser_fn(content, all_paths)

        elif _DOCKERFILE_PATTERN.match(filename):
            summary_hint, references = _parse_dockerfile(content, all_paths)

        elif _DOCKER_COMPOSE_PATTERN.match(filename):
            summary_hint, references = _parse_docker_compose(content, all_paths)

        elif _ENV_PATTERN.match(filename):
            summary_hint, references = _parse_env_example(content, all_paths)

        elif filename.endswith((".yml", ".yaml")):
            summary_hint, references = _parse_yaml_generic(content, path, all_paths)

        else:
            summary_hint = f"Config file: {filename}"

    except Exception as exc:
        logger.warning("Failed to parse config %s: %s", path, exc)
        return ParsedFile(
            path=path,
            language=language or "config",
            kind="config",
            summary_hint=f"Config file: {filename} (parse error)",
            parse_error=str(exc),
        )

    return ParsedFile(
        path=path,
        language=language or "config",
        kind="config",
        references=references,
        summary_hint=summary_hint,
    )
