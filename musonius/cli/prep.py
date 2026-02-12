"""musonius prep — generate optimized agent handoff documents."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import typer

from musonius.cli.utils import console, handle_errors, require_initialized

logger = logging.getLogger(__name__)


@handle_errors
def prep_command(
    epic: str = typer.Argument(None, help="Epic ID to prepare context for."),
    agent: str = typer.Option("claude", "--agent", "-a", help="Target agent."),
    phase: int | None = typer.Option(None, "--phase", "-p", help="Specific phase number."),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path."),
    budget: int = typer.Option(8000, "--budget", "-b", help="Token budget."),
    level: int = typer.Option(1, "--level", "-l", help="Repo map detail level (0-3)."),
    run: bool = typer.Option(False, "--run", help="Auto-handoff to agent CLI after generating."),
) -> None:
    """Generate an optimized context file for a specific agent.

    Creates a handoff document tailored to the target agent's format
    preferences and context window.
    """
    project_root = require_initialized()

    console.print(f"Preparing context for [bold]{agent}[/bold]...")

    try:
        from musonius.context.agents.registry import create_full_registry

        registry = create_full_registry(project_root)
        plugin = registry.get(agent)
        caps = plugin.capabilities()

        effective_budget = min(budget, caps.max_context_tokens)

        # Load real plan, memory, and repo map
        plan_data = _load_latest_plan(project_root, epic)
        memory_entries = _load_memory(project_root, epic)
        repo_map = _load_repo_map(project_root, level, effective_budget)

        # Filter to specific phase if requested
        if phase is not None and plan_data.get("phases"):
            all_phases = plan_data["phases"]
            if 1 <= phase <= len(all_phases):
                plan_data["phases"] = [all_phases[phase - 1]]
                console.print(f"  Phase: {phase} of {len(all_phases)}")
            else:
                console.print(
                    f"[red]Phase {phase} out of range[/red] (1-{len(all_phases)})"
                )
                raise typer.Exit(1)

        task_description = epic or plan_data.get("task_description", "General context")

        handoff = plugin.format_context(
            task=task_description,
            plan=plan_data,
            repo_map=repo_map,
            memory=memory_entries,
            token_budget=effective_budget,
        )

        output_path = Path(output) if output else project_root / f"HANDOFF{caps.file_extension}"

        output_path.write_text(handoff)
        console.print(f"[green]Handoff written to:[/green] {output_path}")
        console.print(f"  Agent: {caps.name}")
        console.print(f"  Token budget: {effective_budget:,}")
        console.print(f"  Plan phases: {len(plan_data.get('phases', []))}")
        console.print(f"  Memory entries: {len(memory_entries)}")
        console.print(f"  Repo map: {'included' if repo_map else 'none'}")

        if run:
            cli_cmd = plugin.handoff_command(output_path)
            if cli_cmd:
                import subprocess

                console.print(f"\n[bold]Running:[/bold] {cli_cmd}")
                subprocess.run(cli_cmd, shell=True, cwd=project_root, check=False)
            else:
                console.print(
                    f"[yellow]No CLI command configured for {caps.name}.[/yellow]"
                )
                console.print("[dim]Use 'musonius agents info' to check agent capabilities.[/dim]")

    except KeyError as e:
        console.print(f"[red]Unknown agent:[/red] {agent}")
        available = ", ".join(registry.list_agents())
        console.print(f"[dim]Available: {available}[/dim]")
        raise typer.Exit(1) from e


def _load_latest_plan(project_root: Path, epic_id: str | None) -> dict[str, Any]:
    """Load the latest plan from .musonius/epics/.

    Args:
        project_root: Project root directory.
        epic_id: Specific epic ID, or None for the most recent.

    Returns:
        Plan dictionary with phases.
    """
    epics_dir = project_root / ".musonius" / "epics"
    if not epics_dir.exists():
        return {}

    # Find the target epic directory
    if epic_id:
        epic_dir = epics_dir / epic_id
        if not epic_dir.is_dir():
            # Try matching partial IDs
            matches = [d for d in epics_dir.iterdir() if d.is_dir() and epic_id in d.name]
            if matches:
                epic_dir = matches[0]
            else:
                logger.debug("Epic %s not found", epic_id)
                return {}
    else:
        # Use most recent epic (by directory modification time)
        epic_dirs = sorted(
            [d for d in epics_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not epic_dirs:
            return {}
        epic_dir = epic_dirs[0]

    # Read spec
    spec_path = epic_dir / "spec.md"
    task_description = ""
    if spec_path.exists():
        task_description = spec_path.read_text().split("\n")[0].lstrip("# ").strip()

    # Read phase files
    phases_dir = epic_dir / "phases"
    phases: list[dict[str, Any]] = []
    if phases_dir.exists():
        for phase_file in sorted(phases_dir.glob("phase-*.md")):
            content = phase_file.read_text()
            lines = content.split("\n")
            title = lines[0].lstrip("# ").strip() if lines else "Untitled"
            description = "\n".join(lines[1:]).strip()
            phases.append({
                "title": title,
                "description": description,
            })

    return {
        "epic_id": epic_dir.name,
        "task_description": task_description,
        "phases": phases,
    }


def _load_memory(project_root: Path, task: str | None) -> list[dict[str, str]]:
    """Load relevant memory entries.

    Args:
        project_root: Project root directory.
        task: Task description for search, or None.

    Returns:
        List of memory entry dicts.
    """
    try:
        from musonius.memory.store import MemoryStore

        db_path = project_root / ".musonius" / "memory" / "decisions.db"
        if not db_path.exists():
            return []
        store = MemoryStore(db_path)
        store.initialize()

        entries: list[dict[str, str]] = []
        decisions = store.search_decisions(task) if task else store.get_all_decisions()
        for d in decisions:
            entries.append({
                "summary": d.get("summary", ""),
                "rationale": d.get("rationale", ""),
                "category": d.get("category", ""),
            })

        conventions = store.get_all_conventions()
        for c in conventions:
            entries.append({
                "summary": f"[{c.get('pattern', '')}] {c.get('rule', '')}",
                "rationale": f"Source: {c.get('source', 'unknown')}",
            })

        return entries
    except Exception as e:
        logger.debug("Failed to load memory: %s", e)
        return []


def _load_repo_map(project_root: Path, level: int, token_budget: int) -> str:
    """Load a repo map from the index cache.

    Args:
        project_root: Project root directory.
        level: Detail level (0-3).
        token_budget: Token budget for the repo map (uses 70% of total).

    Returns:
        Repo map string, or empty string if unavailable.
    """
    try:
        from musonius.config.defaults import INDEX_DIR
        from musonius.context.indexer import Indexer
        from musonius.context.repo_map import RepoMapGenerator

        indexer = Indexer(project_root)
        cache_dir = project_root / ".musonius" / INDEX_DIR
        cached_graph = indexer.load_cache(cache_dir)

        if cached_graph is None:
            return ""

        # Allocate 70% of budget to repo map per spec
        repo_budget = int(token_budget * 0.7)
        gen = RepoMapGenerator(indexer)
        return gen.generate(level=level, token_budget=repo_budget)
    except Exception as e:
        logger.debug("Failed to load repo map: %s", e)
        return ""
