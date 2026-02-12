"""musonius memory — view, search, and manage project memory."""

from __future__ import annotations

import logging

import typer
from rich.table import Table

from musonius.cli.utils import console, handle_errors, require_initialized

logger = logging.getLogger(__name__)

memory_app = typer.Typer(help="View and manage project memory.")


@memory_app.command(name="search")
@handle_errors
def memory_search(
    query: str = typer.Argument(..., help="Search query."),
    category: str | None = typer.Option(None, "--category", "-c", help="Filter by category."),
) -> None:
    """Search project memory for decisions, conventions, and patterns."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    results = store.search_decisions(query)

    if not results:
        console.print(f"[yellow]No results for:[/yellow] {query}")
        return

    table = Table(title=f"Memory Search: {query}", show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("Category", style="cyan")
    table.add_column("Summary")
    table.add_column("Confidence", justify="right")

    for entry in results:
        if category and entry.get("category") != category:
            continue
        table.add_row(
            str(entry.get("id", "")),
            entry.get("category", ""),
            entry.get("summary", ""),
            f"{entry.get('confidence', 1.0):.1f}",
        )

    console.print(table)


@memory_app.command(name="list")
@handle_errors
def memory_list(
    kind: str = typer.Argument(
        "decisions", help="Type to list: decisions, conventions, failures."
    ),
) -> None:
    """List all entries of a specific memory type."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    if kind == "decisions":
        entries = store.get_all_decisions()
    elif kind == "conventions":
        entries = store.get_all_conventions()
    elif kind == "failures":
        entries = store.get_all_failures()
    else:
        console.print(f"[red]Unknown memory type:[/red] {kind}")
        console.print("[dim]Available: decisions, conventions, failures[/dim]")
        raise typer.Exit(1)

    if not entries:
        console.print(f"[yellow]No {kind} recorded yet.[/yellow]")
        return

    table = Table(title=f"Memory: {kind.title()}", show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("Summary")

    for entry in entries:
        table.add_row(str(entry.get("id", "")), entry.get("summary", entry.get("rule", "")))

    console.print(table)


@memory_app.command(name="add")
@handle_errors
def memory_add(
    kind: str = typer.Argument(..., help="Type: decision, convention, failure."),
    summary: str = typer.Argument(..., help="Summary of the entry."),
    rationale: str = typer.Option("", "--rationale", "-r", help="Rationale or details."),
    category: str = typer.Option("general", "--category", "-c", help="Category."),
) -> None:
    """Add an entry to project memory."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    if kind == "decision":
        store.add_decision(summary=summary, rationale=rationale, category=category)
    elif kind == "convention":
        store.add_convention(pattern=category, rule=summary, source="user")
    elif kind == "failure":
        store.add_failure(approach=summary, failure_reason=rationale)
    else:
        console.print(f"[red]Unknown type:[/red] {kind}")
        raise typer.Exit(1)

    console.print(f"[green]Added {kind}:[/green] {summary}")


@memory_app.command(name="show")
@handle_errors
def memory_show(
    kind: str = typer.Argument(..., help="Type: decision, convention, failure."),
    entry_id: int = typer.Argument(..., help="Entry ID to display."),
) -> None:
    """Show detailed information about a specific memory entry."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    if kind == "decision":
        entry = store.get_decision(entry_id)
    elif kind == "convention":
        entry = store.get_convention(entry_id)
    elif kind == "failure":
        entry = store.get_failure(entry_id)
    else:
        console.print(f"[red]Unknown type:[/red] {kind}")
        console.print("[dim]Available: decision, convention, failure[/dim]")
        raise typer.Exit(1)

    if not entry:
        console.print(f"[red]Not found:[/red] {kind} #{entry_id}")
        raise typer.Exit(1)

    from rich.panel import Panel

    lines: list[str] = []
    for key, value in entry.items():
        if value is not None and value != "":
            lines.append(f"[bold]{key}:[/bold] {value}")

    console.print(Panel(
        "\n".join(lines),
        title=f"{kind.title()} #{entry_id}",
        border_style="blue",
    ))


@memory_app.command(name="forget")
@handle_errors
def memory_forget(
    kind: str = typer.Argument(..., help="Type: decision, convention, failure."),
    entry_id: int = typer.Argument(..., help="Entry ID to remove."),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
) -> None:
    """Remove an entry from project memory."""
    project_root = require_initialized()

    from musonius.memory.store import MemoryStore

    store = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    store.initialize()

    # Verify entry exists before deleting
    if kind == "decision":
        entry = store.get_decision(entry_id)
    elif kind == "convention":
        entry = store.get_convention(entry_id)
    elif kind == "failure":
        entry = store.get_failure(entry_id)
    else:
        console.print(f"[red]Unknown type:[/red] {kind}")
        console.print("[dim]Available: decision, convention, failure[/dim]")
        raise typer.Exit(1)

    if not entry:
        console.print(f"[red]Not found:[/red] {kind} #{entry_id}")
        raise typer.Exit(1)

    summary = entry.get("summary", entry.get("rule", entry.get("approach", "")))
    if not force:
        console.print(f"[yellow]About to delete {kind} #{entry_id}:[/yellow] {summary}")
        confirm = typer.confirm("Are you sure?", default=False)
        if not confirm:
            raise typer.Exit()

    if kind == "decision":
        deleted = store.delete_decision(entry_id)
    elif kind == "convention":
        deleted = store.delete_convention(entry_id)
    else:
        deleted = store.delete_failure(entry_id)

    if deleted:
        console.print(f"[green]Removed {kind} #{entry_id}[/green]")
    else:
        console.print(f"[red]Failed to remove {kind} #{entry_id}[/red]")
        raise typer.Exit(1)
