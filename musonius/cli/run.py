"""musonius run — launch the Textual TUI dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from musonius.cli.utils import console, handle_errors, require_initialized

logger = logging.getLogger(__name__)


@handle_errors
def run_command(
    task: str = typer.Argument("", help="Task description (optional)."),
) -> None:
    """Launch the Musonius TUI dashboard.

    Opens a split-pane terminal UI with pipeline progress,
    operation output, memory sidebar, and persistent status bar.

    Requires: pip install musonius[tui]
    """
    project_root = require_initialized()

    from musonius.cli.dashboard import check_textual_available, run_dashboard

    if not check_textual_available():
        console.print("[yellow]Textual is not installed.[/yellow]")
        console.print("Install it with: [bold]pip install musonius\\[tui][/bold]")
        console.print()
        console.print("[dim]Falling back to enhanced status display...[/dim]\n")
        from musonius.cli.display import render_status_dashboard

        render_status_dashboard(project_root)
        return

    run_dashboard(project_root=project_root, task=task)
