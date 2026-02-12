"""musonius rollback — restore to a phase checkpoint."""

from __future__ import annotations

import logging
import subprocess

import typer
from rich.panel import Panel

from musonius.cli.utils import console, handle_errors, require_initialized

logger = logging.getLogger(__name__)


@handle_errors
def rollback_command(
    epic: str = typer.Argument(..., help="Epic ID to rollback (e.g., epic-abc12345)."),
    phase: str = typer.Argument(..., help="Phase to restore (e.g., phase-1)."),
    hard: bool = typer.Option(False, "--hard", help="Discard all uncommitted changes."),
) -> None:
    """Restore the project to a phase checkpoint.

    Uses git tags created during phase execution to restore the codebase
    to the state at the start or end of a specific phase.
    """
    project_root = require_initialized()

    tag_name = f"musonius/{epic}/{phase}-start"
    console.print(Panel(f"Rollback to: {tag_name}", title="Rollback", border_style="yellow"))

    # Check if tag exists
    try:
        result = subprocess.run(
            ["git", "tag", "-l", tag_name],
            capture_output=True,
            text=True,
            cwd=project_root,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[red]Git error:[/red] {e}")
        raise typer.Exit(1) from e

    if not result.stdout.strip():
        # List available tags for this epic
        try:
            tags_result = subprocess.run(
                ["git", "tag", "-l", f"musonius/{epic}/*"],
                capture_output=True,
                text=True,
                cwd=project_root,
                check=True,
            )
            available = tags_result.stdout.strip()
        except Exception:
            available = ""

        console.print(f"[red]Tag not found:[/red] {tag_name}")
        if available:
            console.print(f"\nAvailable checkpoints:\n{available}")
        else:
            console.print(f"[dim]No checkpoints found for {epic}[/dim]")
        raise typer.Exit(1)

    # Check for uncommitted changes
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=project_root,
            check=True,
        )
    except Exception:
        status_result = None

    if status_result and status_result.stdout.strip() and not hard:
        console.print("[yellow]Warning:[/yellow] You have uncommitted changes.")
        console.print("Use --hard to discard them, or commit/stash first.")
        raise typer.Exit(1)

    # Stash changes if not hard
    if status_result and status_result.stdout.strip() and hard:
        console.print("[yellow]Discarding uncommitted changes...[/yellow]")

    # Create a backup tag before rolling back
    import contextlib

    with contextlib.suppress(Exception):
        subprocess.run(
            ["git", "tag", f"musonius/rollback-backup/{epic}"],
            capture_output=True,
            text=True,
            cwd=project_root,
            check=False,
        )

    # Perform the rollback
    checkout_args = ["git", "checkout", tag_name]
    if hard:
        # Reset to the tag
        checkout_args = ["git", "reset", "--hard", tag_name]

    try:
        subprocess.run(
            checkout_args,
            capture_output=True,
            text=True,
            cwd=project_root,
            check=True,
        )
        console.print(f"[green]Rolled back to:[/green] {tag_name}")
        console.print("[dim]A backup tag was created at musonius/rollback-backup/[/dim]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Rollback failed:[/red] {e.stderr or e}")
        raise typer.Exit(1) from e
