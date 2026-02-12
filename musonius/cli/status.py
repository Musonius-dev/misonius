"""musonius status — show project status, token usage, and progress."""

from __future__ import annotations

import logging

from rich.panel import Panel
from rich.table import Table

from musonius.cli.utils import console, handle_errors, require_initialized

logger = logging.getLogger(__name__)


@handle_errors
def status_command() -> None:
    """Show project status, token usage, and memory statistics."""
    project_root = require_initialized()
    musonius_dir = project_root / ".musonius"

    console.print(Panel(f"Project: {project_root.name}", title="Musonius Status", border_style="blue"))

    # Directory stats
    table = Table(show_header=True)
    table.add_column("Component", style="cyan")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    # Check index
    index_dir = musonius_dir / "index"
    if index_dir.exists():
        files = list(index_dir.glob("*"))
        table.add_row("Index", "[green]Available[/green]", f"{len(files)} cached files")
    else:
        table.add_row("Index", "[yellow]Not built[/yellow]", "Run musonius init")

    # Check memory
    memory_dir = musonius_dir / "memory"
    if memory_dir.exists():
        db_path = memory_dir / "decisions.db"
        if db_path.exists():
            try:
                from musonius.memory.store import MemoryStore

                store = MemoryStore(db_path)
                store.initialize()
                decisions = store.get_all_decisions()
                conventions = store.get_all_conventions()
                failures = store.get_all_failures()
                table.add_row(
                    "Memory",
                    "[green]Active[/green]",
                    f"{len(decisions)} decisions, {len(conventions)} conventions, {len(failures)} failures",
                )
            except Exception:
                table.add_row("Memory", "[yellow]Error[/yellow]", "Database issue")
        else:
            table.add_row("Memory", "[yellow]Empty[/yellow]", "No entries yet")
    else:
        table.add_row("Memory", "[red]Missing[/red]", "Run musonius init")

    # Check epics with phase progress
    epics_dir = musonius_dir / "epics"
    if epics_dir.exists():
        epics = [d for d in epics_dir.iterdir() if d.is_dir()]
        table.add_row("Epics", "[green]Available[/green]", f"{len(epics)} epics")
    else:
        epics = []
        table.add_row("Epics", "[yellow]None[/yellow]", "Run musonius plan")

    # Config and model routing
    config_path = musonius_dir / "config.yaml"
    if config_path.exists():
        from musonius.config.loader import load_config

        config = load_config(project_root)
        models = config.get("models", {})
        model_info = ", ".join(
            f"{role}={model}"
            for role, model in sorted(models.items())
            if role != "custom" and isinstance(model, str)
        )
        table.add_row("Config", "[green]Found[/green]", model_info or str(config_path))
    else:
        table.add_row("Config", "[red]Missing[/red]", "")

    console.print(table)

    # Show phase progress for each epic
    if epics:
        console.print()
        phase_table = Table(title="Epic Progress", show_header=True)
        phase_table.add_column("Epic", style="cyan")
        phase_table.add_column("Phases", justify="right")
        phase_table.add_column("Task")

        for epic_dir in sorted(epics, key=lambda d: d.stat().st_mtime, reverse=True):
            phases_dir = epic_dir / "phases"
            phase_count = len(list(phases_dir.glob("phase-*.md"))) if phases_dir.exists() else 0

            # Read task description from spec
            spec_path = epic_dir / "spec.md"
            task_desc = ""
            if spec_path.exists():
                first_line = spec_path.read_text().split("\n")[0]
                task_desc = first_line.lstrip("# ").strip()

            phase_table.add_row(
                epic_dir.name,
                str(phase_count),
                task_desc[:60] + ("..." if len(task_desc) > 60 else ""),
            )

        console.print(phase_table)
