"""musonius history — view past activity, session context, and epic lifecycle."""

from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from musonius.cli.utils import console, handle_errors, require_initialized

logger = logging.getLogger(__name__)

history_app = typer.Typer(
    name="history",
    help="View task history, session context, and epic lifecycle.",
    no_args_is_help=True,
)


@history_app.command(name="log")
@handle_errors
def log_command(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of entries to show."),
    command: Optional[str] = typer.Option(None, "--command", "-c", help="Filter by command name."),
    epic: Optional[str] = typer.Option(None, "--epic", "-e", help="Filter by epic ID."),
) -> None:
    """Show the activity log — what commands were run, when, and their outcomes."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    entries = store.get_activity_log(limit=limit, command=command, epic_id=epic)
    store.close()

    if not entries:
        console.print("[dim]No activity recorded yet. Run some commands first.[/dim]")
        return

    table = Table(title="Activity Log", show_header=True)
    table.add_column("Time", style="dim", min_width=19)
    table.add_column("Command", style="cyan")
    table.add_column("Args", max_width=30)
    table.add_column("Status")
    table.add_column("Outcome", max_width=40)
    table.add_column("Duration", style="dim", justify="right")

    for entry in entries:
        status = entry.get("status", "")
        if status == "completed":
            status_display = "[green]completed[/green]"
        elif status == "failed":
            status_display = "[red]failed[/red]"
        else:
            status_display = f"[yellow]{status}[/yellow]"

        duration = entry.get("duration_ms", 0)
        if duration and duration > 0:
            if duration > 60000:
                dur_str = f"{duration / 60000:.1f}m"
            elif duration > 1000:
                dur_str = f"{duration / 1000:.1f}s"
            else:
                dur_str = f"{duration:.0f}ms"
        else:
            dur_str = ""

        timestamp = str(entry.get("created_at", ""))[:19]
        args = entry.get("args", "") or ""
        outcome = entry.get("outcome", "") or ""

        table.add_row(
            timestamp,
            entry.get("command", ""),
            args[:30],
            status_display,
            outcome[:40],
            dur_str,
        )

    console.print(table)


@history_app.command(name="epics")
@handle_errors
def epics_command() -> None:
    """Show epic lifecycle status — what's planned, in progress, verified, or complete."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    epics = store.get_all_epic_statuses()
    store.close()

    if not epics:
        console.print("[dim]No epics tracked yet. Run musonius plan to create one.[/dim]")
        return

    table = Table(title="Epic Lifecycle", show_header=True)
    table.add_column("Epic ID", style="cyan")
    table.add_column("Status")
    table.add_column("Phase", style="dim")
    table.add_column("Task")
    table.add_column("Updated", style="dim")

    status_colors = {
        "planned": "blue",
        "in_progress": "yellow",
        "verified": "green",
        "complete": "bold green",
        "failed": "red",
    }

    for epic in epics:
        status = epic.get("status", "unknown")
        color = status_colors.get(status, "dim")
        status_display = f"[{color}]{status}[/{color}]"

        task = epic.get("task_description", "") or ""
        phase = epic.get("current_phase", "") or ""
        updated = str(epic.get("updated_at", ""))[:19]

        table.add_row(
            epic.get("epic_id", ""),
            status_display,
            phase,
            task[:50] + ("..." if len(task) > 50 else ""),
            updated,
        )

    console.print(table)


@history_app.command(name="context")
@handle_errors
def context_command(
    epic: Optional[str] = typer.Option(None, "--epic", "-e", help="Filter by epic ID."),
    context_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by type (clarification, preference, note)."
    ),
    limit: int = typer.Option(30, "--limit", "-n", help="Number of entries to show."),
) -> None:
    """Show saved session context — clarifications, preferences, and notes."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    entries = store.get_session_context(
        context_type=context_type,
        epic_id=epic,
        limit=limit,
    )
    store.close()

    if not entries:
        console.print("[dim]No session context saved yet.[/dim]")
        return

    table = Table(title="Session Context", show_header=True)
    table.add_column("Time", style="dim", min_width=19)
    table.add_column("Type", style="cyan")
    table.add_column("Key", max_width=40)
    table.add_column("Value", max_width=50)

    for entry in entries:
        timestamp = str(entry.get("created_at", ""))[:19]
        key = entry.get("key", "")
        value = entry.get("value", "")

        table.add_row(
            timestamp,
            entry.get("context_type", ""),
            key[:40],
            value[:50] + ("..." if len(value) > 50 else ""),
        )

    console.print(table)


@history_app.command(name="summary")
@handle_errors
def summary_command() -> None:
    """Show a quick summary of project history and current state."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    # Gather stats
    activities = store.get_activity_log(limit=1000)
    epics = store.get_all_epic_statuses()
    decisions = store.get_all_decisions()
    failures = store.get_all_failures()
    conventions = store.get_all_conventions()

    # Count by command
    command_counts: dict[str, int] = {}
    for a in activities:
        cmd = a.get("command", "unknown")
        command_counts[cmd] = command_counts.get(cmd, 0) + 1

    # Count by epic status
    status_counts: dict[str, int] = {}
    for e in epics:
        s = e.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    store.close()

    console.print(Panel(f"Project: {project_root.name}", title="History Summary", border_style="blue"))

    parts: list[str] = []

    # Activity stats
    if activities:
        total = len(activities)
        completed = sum(1 for a in activities if a.get("status") == "completed")
        failed = sum(1 for a in activities if a.get("status") == "failed")
        parts.append(f"[bold]Activity:[/bold] {total} commands run ({completed} completed, {failed} failed)")

        cmd_str = ", ".join(f"{cmd}: {count}" for cmd, count in sorted(command_counts.items()))
        parts.append(f"  Commands: {cmd_str}")

        # Last activity
        last = activities[0]
        parts.append(f"  Last: [cyan]{last.get('command')}[/cyan] at {str(last.get('created_at', ''))[:19]}")
    else:
        parts.append("[bold]Activity:[/bold] No commands run yet")

    # Epic stats
    parts.append("")
    if epics:
        status_str = ", ".join(f"{s}: {c}" for s, c in sorted(status_counts.items()))
        parts.append(f"[bold]Epics:[/bold] {len(epics)} tracked ({status_str})")
    else:
        parts.append("[bold]Epics:[/bold] None tracked yet")

    # Memory stats
    parts.append("")
    parts.append(
        f"[bold]Memory:[/bold] {len(decisions)} decisions, "
        f"{len(conventions)} conventions, {len(failures)} failures"
    )

    console.print("\n".join(parts))
