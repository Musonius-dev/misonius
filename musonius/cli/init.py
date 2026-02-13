"""musonius init — initialize a project for Musonius."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from musonius.cli.utils import console, find_project_root, handle_errors
from musonius.config.defaults import (
    EPICS_DIR,
    INDEX_DIR,
    MEMORY_DIR,
    MUSONIUS_DIR,
    SOT_DIR,
    TEMPLATES_DIR,
)
from musonius.config.loader import load_config, save_config

logger = logging.getLogger(__name__)


@handle_errors
def init_command(
    auto: bool = typer.Option(False, "--auto", "-a", help="Skip interactive prompts."),
    language: str | None = typer.Option(None, "--language", "-l", help="Primary project language."),
) -> None:
    """Initialize Musonius for the current project.

    Creates the .musonius/ directory structure, indexes the codebase,
    and detects project conventions.
    """
    project_root = find_project_root()
    musonius_dir = project_root / MUSONIUS_DIR

    if musonius_dir.exists():
        console.print(
            f"[yellow]Warning:[/yellow] {MUSONIUS_DIR}/ already exists at {project_root}"
        )
        if not auto:
            reinit = typer.confirm("Re-initialize?", default=False)
            if not reinit:
                raise typer.Exit()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Create directory structure
        task = progress.add_task("Creating directory structure...", total=None)
        _create_directory_structure(musonius_dir)
        progress.update(task, description="Directory structure created.")

        # Save default config
        task = progress.add_task("Writing configuration...", total=None)
        config = load_config(project_root)
        if language:
            config["project"]["language"] = language
        save_config(project_root, config)
        progress.update(task, description="Configuration saved.")

        # Index codebase
        task = progress.add_task("Indexing codebase with tree-sitter...", total=None)
        try:
            from musonius.context.indexer import Indexer

            indexer = Indexer(project_root)
            graph = indexer.index_codebase()
            file_count = graph.file_count
            symbol_count = graph.symbol_count

            # Persist index cache for later use by plan/prep
            cache_dir = musonius_dir / INDEX_DIR
            indexer.save_cache(graph, cache_dir)

            progress.update(
                task,
                description=f"Indexed {file_count} files, {symbol_count} symbols.",
            )
        except Exception as e:
            logger.warning("Indexing failed: %s", e)
            progress.update(task, description=f"[yellow]Indexing skipped:[/yellow] {e}")
            file_count = 0
            symbol_count = 0

        # Initialize memory store
        task = progress.add_task("Initializing memory store...", total=None)
        store = None
        try:
            from musonius.memory.store import MemoryStore

            store = MemoryStore(musonius_dir / MEMORY_DIR / "decisions.db")
            store.initialize()
            progress.update(task, description="Memory store initialized.")
        except Exception as e:
            logger.warning("Memory initialization failed: %s", e)
            progress.update(task, description=f"[yellow]Memory skipped:[/yellow] {e}")

        # Detect coding conventions
        convention_count = 0
        task = progress.add_task("Detecting coding conventions...", total=None)
        try:
            from musonius.memory.convention_detector import (
                detect_conventions,
                store_conventions,
            )

            report = detect_conventions(
                project_root,
                graph=graph if "graph" in dir() else None,
            )
            if store is not None:
                convention_count = store_conventions(report, store)
            progress.update(
                task,
                description=f"Detected {len(report.conventions)} conventions"
                f" ({convention_count} stored).",
            )
        except Exception as e:
            logger.warning("Convention detection failed: %s", e)
            progress.update(
                task, description=f"[yellow]Convention detection skipped:[/yellow] {e}"
            )

    # Log activity
    try:
        from musonius.memory.activity import track_activity

        with track_activity(project_root, "init") as activity:
            activity["outcome"] = (
                f"Indexed {file_count} files, {symbol_count} symbols, "
                f"{convention_count} conventions"
            )
    except Exception:
        pass  # Activity tracking is non-critical

    console.print()
    console.print(f"[green]Musonius initialized[/green] at {project_root}")
    console.print(f"  Files indexed: {file_count}")
    console.print(f"  Symbols found: {symbol_count}")
    console.print(f"  Conventions detected: {convention_count}")
    console.print()
    console.print("Next steps:")
    console.print("  [bold]musonius plan \"your task\"[/bold]  — Generate a plan")
    console.print("  [bold]musonius prep --agent claude[/bold]  — Generate handoff")


def _create_directory_structure(musonius_dir: Path) -> None:
    """Create the .musonius/ directory tree."""
    dirs = [
        musonius_dir,
        musonius_dir / INDEX_DIR,
        musonius_dir / MEMORY_DIR,
        musonius_dir / EPICS_DIR,
        musonius_dir / SOT_DIR,
        musonius_dir / TEMPLATES_DIR,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
