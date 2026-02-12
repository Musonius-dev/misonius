"""Shared CLI utilities — console, error handling, project detection."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from musonius.config.defaults import MUSONIUS_DIR

console = Console()
error_console = Console(stderr=True)
logger = logging.getLogger(__name__)


def find_project_root() -> Path:
    """Find the nearest directory containing .musonius/ or .git/.

    Walks up from cwd to find the project root.

    Returns:
        Path to the project root directory.

    Raises:
        typer.Exit: If no project root is found.
    """
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / MUSONIUS_DIR).is_dir():
            return parent
        if (parent / ".git").exists():
            return parent
    return current


def require_initialized() -> Path:
    """Require that the project has been initialized with `musonius init`.

    Returns:
        Path to the project root.

    Raises:
        typer.Exit: If the project is not initialized.
    """
    root = find_project_root()
    if not (root / MUSONIUS_DIR).is_dir():
        error_console.print(
            "[red]Error:[/red] Project not initialized. Run [bold]musonius init[/bold] first."
        )
        raise typer.Exit(1)
    return root


def handle_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that catches exceptions and shows user-friendly messages."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except KeyboardInterrupt:
            error_console.print("\n[yellow]Interrupted.[/yellow]")
            raise typer.Exit(130) from None
        except Exception as e:
            logger.exception("Unexpected error")
            error_console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from e

    return wrapper
