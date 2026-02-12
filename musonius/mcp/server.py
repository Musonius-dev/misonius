"""MCP server — exposes Musonius tools for universal IDE integration.

Provides 6 tools via FastMCP that any MCP-compatible client (Claude Code,
Cursor, VS Code, etc.) can call to access pre-computed codebase context,
persistent project memory, and verification.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "musonius",
    instructions=(
        "Musonius is an AI coding multiplier. It pre-computes codebase context, "
        "maintains persistent project memory, and generates optimized handoff "
        "documents. Use these tools to get surgical context instead of exploring."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Find the project root containing .musonius/."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".musonius").is_dir():
            return parent
    return current


def _require_project() -> Path:
    """Require an initialized Musonius project.

    Returns:
        Path to the project root.

    Raises:
        RuntimeError: If no initialized project is found.
    """
    root = _find_project_root()
    if not (root / ".musonius").is_dir():
        raise RuntimeError(
            "No initialized Musonius project found. Run `musonius init` first."
        )
    return root


def _get_memory_context(project_root: Path, query: str) -> list[dict[str, str]]:
    """Get memory entries relevant to a query."""
    db_path = project_root / ".musonius" / "memory" / "decisions.db"
    if not db_path.exists():
        return []

    try:
        from musonius.memory.store import MemoryStore

        store = MemoryStore(db_path)
        store.initialize()

        entries: list[dict[str, str]] = []
        decisions = store.search_decisions(query) if query else store.get_all_decisions()

        for d in decisions[:10]:
            entries.append({
                "type": "decision",
                "summary": d.get("summary", ""),
                "rationale": d.get("rationale", ""),
            })

        return entries
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Business logic (testable, no MCP dependency)
# ---------------------------------------------------------------------------


def _get_plan_impl(project_root: Path, epic_id: str | None = None) -> dict[str, Any]:
    """Get the current implementation plan with optimized context.

    Args:
        project_root: Path to the project root.
        epic_id: Specific epic ID, or None for the most recent plan.

    Returns:
        Plan dictionary with phases, files, and acceptance criteria.
    """
    epics_dir = project_root / ".musonius" / "epics"

    if not epics_dir.exists():
        return {"error": "No plans found. Run `musonius plan` first."}

    # Find target epic
    if epic_id:
        epic_dir = epics_dir / epic_id
        if not epic_dir.is_dir():
            matches = [
                d for d in epics_dir.iterdir() if d.is_dir() and epic_id in d.name
            ]
            if not matches:
                return {"error": f"Epic '{epic_id}' not found."}
            epic_dir = matches[0]
    else:
        epic_dirs = sorted(
            [d for d in epics_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not epic_dirs:
            return {"error": "No plans found."}
        epic_dir = epic_dirs[0]

    # Read spec
    spec_path = epic_dir / "spec.md"
    spec_content = spec_path.read_text() if spec_path.exists() else ""

    # Read phases
    phases: list[dict[str, str]] = []
    phases_dir = epic_dir / "phases"
    if phases_dir.exists():
        for phase_file in sorted(phases_dir.glob("phase-*.md")):
            content = phase_file.read_text()
            lines = content.split("\n")
            title = lines[0].lstrip("# ").strip() if lines else "Untitled"
            phases.append({
                "title": title,
                "content": content,
                "file": phase_file.name,
            })

    return {
        "epic_id": epic_dir.name,
        "spec": spec_content,
        "phases": phases,
        "phase_count": len(phases),
    }


def _get_context_impl(
    project_root: Path,
    file_path: str | None = None,
    function_name: str | None = None,
    token_budget: int = 8000,
    detail_level: int = 1,
) -> dict[str, Any]:
    """Get token-budgeted context for a file or function.

    Args:
        project_root: Path to the project root.
        file_path: Specific file to get context for, or None for general.
        function_name: Specific function to focus on.
        token_budget: Maximum tokens for the returned context.
        detail_level: Repo map detail level (0=paths, 1=signatures, 2=docs, 3=full).

    Returns:
        Context dictionary with repo map, symbols, and memory.
    """
    try:
        from musonius.config.defaults import INDEX_DIR
        from musonius.context.indexer import Indexer
        from musonius.context.repo_map import RepoMapGenerator

        indexer = Indexer(project_root)
        cache_dir = project_root / ".musonius" / INDEX_DIR

        # Try loading from cache first
        graph = indexer.load_cache(cache_dir)
        if graph is None:
            graph = indexer.index_codebase()

        result: dict[str, Any] = {
            "file_count": graph.file_count,
            "symbol_count": graph.symbol_count,
        }

        # Generate repo map
        relevant_files = [Path(file_path)] if file_path else None
        gen = RepoMapGenerator(indexer)
        repo_map = gen.generate(
            level=detail_level,
            relevant_files=relevant_files,
            token_budget=token_budget,
        )
        result["repo_map"] = repo_map

        # If specific file requested, add symbol details
        if file_path:
            symbols = graph.get_file_symbols(Path(file_path))
            result["symbols"] = [
                {
                    "name": s.qualified_name,
                    "type": s.type,
                    "line": s.line_number,
                    "signature": s.signature,
                    "docstring": s.docstring,
                }
                for s in symbols
                if function_name is None or s.name == function_name
            ]
            result["dependencies"] = graph.get_dependencies(file_path)

        # Add memory
        result["memory"] = _get_memory_context(project_root, file_path or "")

        return result

    except Exception as e:
        logger.error("Context retrieval failed: %s", e)
        return {"error": str(e)}


def _verify_impl(
    project_root: Path,
    staged_only: bool = False,
    epic_id: str | None = None,
) -> dict[str, Any]:
    """Trigger verification of current changes against the active plan.

    Args:
        project_root: Path to the project root.
        staged_only: Only verify staged changes.
        epic_id: Epic ID to verify against.

    Returns:
        Verification results with severity-categorized findings.
    """
    import subprocess

    # Get diff
    diff_cmd = ["git", "diff"]
    if staged_only:
        diff_cmd.append("--staged")

    try:
        proc = subprocess.run(
            diff_cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            check=True,
        )
        diff = proc.stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return {"error": f"Failed to get git diff: {e}"}

    if not diff.strip():
        return {"status": "clean", "findings": [], "message": "No changes to verify."}

    # Load plan
    plan_result = _get_plan_impl(project_root, epic_id)
    plan = {"phases": plan_result.get("phases", [])}

    # Run verification
    from musonius.verification.engine import VerificationEngine

    engine = VerificationEngine()
    result = engine.verify_diff(diff=diff, plan=plan, use_llm=False)

    return {
        "status": "passed" if result.passed else "failed",
        "summary": result.diff_summary,
        "findings": [
            {
                "severity": f.severity.value,
                "category": f.category,
                "message": f.message,
                "file_path": f.file_path,
                "suggestion": f.suggestion,
            }
            for f in result.findings
        ],
        "critical_count": result.critical_count,
        "major_count": result.major_count,
        "total_findings": len(result.findings),
    }


def _memory_query_impl(
    project_root: Path,
    query: str,
    memory_type: str = "all",
) -> dict[str, Any]:
    """Search project memory for decisions, conventions, and patterns.

    Args:
        project_root: Path to the project root.
        query: Search query string.
        memory_type: Type to search: "decisions", "conventions", "failures", or "all".

    Returns:
        Matching memory entries.
    """
    db_path = project_root / ".musonius" / "memory" / "decisions.db"

    if not db_path.exists():
        return {"results": [], "message": "Memory store not initialized."}

    from musonius.memory.store import MemoryStore

    store = MemoryStore(db_path)
    store.initialize()

    results: dict[str, list[dict[str, Any]]] = {}

    if memory_type in ("all", "decisions"):
        results["decisions"] = store.search_decisions(query)

    if memory_type in ("all", "failures"):
        results["failures"] = store.search_failures(query)

    if memory_type in ("all", "conventions"):
        all_conventions = store.get_all_conventions()
        query_lower = query.lower()
        results["conventions"] = [
            c
            for c in all_conventions
            if query_lower in c.get("rule", "").lower()
            or query_lower in c.get("pattern", "").lower()
        ]

    total = sum(len(v) for v in results.values())
    return {"query": query, "total_results": total, "results": results}


def _record_decision_impl(
    project_root: Path,
    summary: str,
    rationale: str = "",
    category: str = "architecture",
    epic_id: str | None = None,
    files_affected: list[str] | None = None,
) -> dict[str, Any]:
    """Add a new architectural decision to project memory.

    Args:
        project_root: Path to the project root.
        summary: Brief summary of the decision.
        rationale: Why this decision was made.
        category: Decision category (architecture, dependency, pattern).
        epic_id: Associated epic ID, if any.
        files_affected: List of affected file paths.

    Returns:
        Confirmation with the new decision ID.
    """
    db_path = project_root / ".musonius" / "memory" / "decisions.db"

    from musonius.memory.store import MemoryStore

    store = MemoryStore(db_path)
    store.initialize()

    decision_id = store.add_decision(
        summary=summary,
        rationale=rationale,
        category=category,
        epic_id=epic_id,
        files_affected=files_affected,
    )

    return {
        "id": decision_id,
        "summary": summary,
        "category": category,
        "message": "Decision recorded successfully.",
    }


def _status_impl(project_root: Path) -> dict[str, Any]:
    """Get project health stats: file count, symbol count, memory, epics.

    Args:
        project_root: Path to the project root.

    Returns:
        Project status dictionary.
    """
    musonius_dir = project_root / ".musonius"
    status: dict[str, Any] = {
        "project_root": str(project_root),
        "initialized": musonius_dir.is_dir(),
    }

    if not musonius_dir.is_dir():
        return status

    # Index stats
    try:
        from musonius.config.defaults import INDEX_DIR
        from musonius.context.indexer import Indexer

        indexer = Indexer(project_root)
        cache_dir = musonius_dir / INDEX_DIR
        graph = indexer.load_cache(cache_dir)

        if graph:
            status["index"] = {
                "file_count": graph.file_count,
                "symbol_count": graph.symbol_count,
                "cached": True,
            }
        else:
            status["index"] = {"cached": False, "message": "Run `musonius init` to index."}
    except Exception as e:
        status["index"] = {"error": str(e)}

    # Memory stats
    db_path = musonius_dir / "memory" / "decisions.db"
    if db_path.exists():
        try:
            from musonius.memory.store import MemoryStore

            store = MemoryStore(db_path)
            store.initialize()
            status["memory"] = {
                "decisions": len(store.get_all_decisions()),
                "conventions": len(store.get_all_conventions()),
                "failures": len(store.get_all_failures()),
            }
        except Exception as e:
            status["memory"] = {"error": str(e)}
    else:
        status["memory"] = {"initialized": False}

    # Epic stats
    epics_dir = musonius_dir / "epics"
    if epics_dir.exists():
        epic_dirs = [d for d in epics_dir.iterdir() if d.is_dir()]
        status["epics"] = {
            "count": len(epic_dirs),
            "ids": [d.name for d in sorted(epic_dirs)],
        }
    else:
        status["epics"] = {"count": 0}

    return status


# ---------------------------------------------------------------------------
# MCP tool wrappers — rich descriptions for downstream agents
# ---------------------------------------------------------------------------


@mcp.tool()
def musonius_get_plan(epic_id: str | None = None) -> dict[str, Any]:
    """Get the current implementation plan with phased context.

    Returns the active plan broken into phases, each with a title,
    description, file list, and acceptance criteria. If no epic_id is
    given, returns the most recently modified plan.

    Use this FIRST when starting work on a task — it tells you what to
    build, in what order, and what files to touch.

    Args:
        epic_id: Specific epic ID (e.g. "epic-001"), or omit for latest.

    Returns:
        Plan with epic_id, spec, phases (title/content/file), phase_count.
    """
    return _get_plan_impl(_require_project(), epic_id)


@mcp.tool()
def musonius_get_context(
    file_path: str | None = None,
    function_name: str | None = None,
    token_budget: int = 8000,
    detail_level: int = 1,
) -> dict[str, Any]:
    """Get pre-computed, token-budgeted codebase context.

    Returns a repo map at the requested detail level, symbols for a
    specific file or function, dependency information, and relevant
    project memory (past decisions, conventions, known failures).

    This replaces manual codebase exploration — everything you need
    to understand the code is pre-indexed and returned within budget.

    Detail levels:
      0 = file paths only (cheapest)
      1 = paths + function/class signatures
      2 = signatures + docstrings
      3 = full file contents (most expensive)

    Args:
        file_path: Focus on a specific file (e.g. "musonius/memory/store.py").
        function_name: Focus on a specific function within that file.
        token_budget: Max tokens for the repo map (default 8000).
        detail_level: 0-3, controls how much detail is included.

    Returns:
        Dict with repo_map, file_count, symbol_count, symbols, dependencies, memory.
    """
    return _get_context_impl(
        _require_project(), file_path, function_name, token_budget, detail_level
    )


@mcp.tool()
def musonius_verify(
    staged_only: bool = False,
    epic_id: str | None = None,
) -> dict[str, Any]:
    """Verify current code changes against the active plan.

    Runs the full verification pipeline on your git diff:
    1. Extracts changed files from git diff (staged or working tree)
    2. Checks plan coverage (missing files, extra files)
    3. Runs heuristic checks (print statements, bare excepts, secrets)
    4. Returns severity-categorized findings

    Call this AFTER implementing changes to catch issues before commit.

    Args:
        staged_only: If True, only verify staged (git add) changes.
        epic_id: Verify against a specific epic's plan.

    Returns:
        Dict with status (passed/failed/clean), findings list, counts.
    """
    return _verify_impl(_require_project(), staged_only, epic_id)


@mcp.tool()
def musonius_memory_query(
    query: str,
    memory_type: str = "all",
) -> dict[str, Any]:
    """Search persistent project memory for decisions, conventions, and failures.

    The memory store accumulates tribal knowledge across sessions:
    - **decisions**: Architecture choices with rationale ("Use SQLite because...")
    - **conventions**: Detected code patterns ("snake_case for functions")
    - **failures**: Approaches that failed and why ("Redis caching failed because...")

    Query this BEFORE implementing to learn from past context and avoid
    repeating known mistakes.

    Args:
        query: Search term (e.g. "auth", "caching", "database").
        memory_type: Filter to "decisions", "conventions", "failures", or "all".

    Returns:
        Dict with query, total_results, and results grouped by type.
    """
    return _memory_query_impl(_require_project(), query, memory_type)


@mcp.tool()
def musonius_record_decision(
    summary: str,
    rationale: str = "",
    category: str = "architecture",
    epic_id: str | None = None,
    files_affected: list[str] | None = None,
) -> dict[str, Any]:
    """Record an architectural decision in persistent project memory.

    Decisions persist across sessions and tools. Future agents (and
    humans) running `musonius_memory_query` will find this decision
    and its rationale, preventing repeated debates or mistakes.

    Use this when you make a significant choice: library selection,
    API design, data model changes, infrastructure decisions.

    Args:
        summary: Brief summary (e.g. "Use SQLite for persistence").
        rationale: Why this was chosen (e.g. "No external deps, good enough for v0.1").
        category: One of "architecture", "dependency", "pattern", "convention".
        epic_id: Link to a specific epic (e.g. "epic-001").
        files_affected: Files this decision impacts (e.g. ["musonius/memory/store.py"]).

    Returns:
        Dict with id, summary, category, and confirmation message.
    """
    return _record_decision_impl(
        _require_project(), summary, rationale, category, epic_id, files_affected
    )


@mcp.tool()
def musonius_status() -> dict[str, Any]:
    """Get project health: index stats, memory counts, epic list.

    Quick overview of the Musonius project state — how many files are
    indexed, how many decisions/conventions/failures are stored, and
    which epics exist. Use this to orient yourself in a new session.

    Returns:
        Dict with project_root, index stats, memory counts, epic IDs.
    """
    return _status_impl(_require_project())


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def run_server() -> None:
    """Run the MCP server via stdio transport."""
    mcp.run()
