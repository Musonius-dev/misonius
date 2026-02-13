"""musonius init — initialize a project for Musonius."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table
from musonius.cli.display import PipelineProgress
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


# ---------------------------------------------------------------------------
# Existing-project inspection
# ---------------------------------------------------------------------------


def _gather_existing_stats(musonius_dir: Path) -> dict[str, str | int]:
    """Inspect an existing .musonius/ directory and return summary stats."""
    stats: dict[str, str | int] = {
        "files_indexed": 0,
        "decisions": 0,
        "conventions": 0,
        "failures": 0,
        "epics": 0,
        "last_init": "unknown",
    }

    # Index
    index_dir = musonius_dir / INDEX_DIR
    if index_dir.exists():
        stats["files_indexed"] = len(list(index_dir.glob("*")))

    # Memory
    db_path = musonius_dir / MEMORY_DIR / "decisions.db"
    if db_path.exists():
        try:
            from musonius.memory.store import MemoryStore

            store = MemoryStore(db_path)
            store.initialize()
            stats["decisions"] = len(store.get_all_decisions())
            stats["conventions"] = len(store.get_all_conventions())
            stats["failures"] = len(store.get_all_failures())
            store.close()
        except Exception:
            pass

    # Epics
    epics_dir = musonius_dir / EPICS_DIR
    if epics_dir.exists():
        stats["epics"] = len([d for d in epics_dir.iterdir() if d.is_dir()])

    # Last modified (config as proxy for last init)
    config_path = musonius_dir / "config.yaml"
    if config_path.exists():
        mtime = config_path.stat().st_mtime
        stats["last_init"] = datetime.fromtimestamp(mtime).strftime("%b %d, %Y at %H:%M")

    return stats


def _show_existing_project(musonius_dir: Path, project_root: Path) -> str:
    """Show what's already initialized and prompt for action.

    Returns:
        Action string: 'update', 'reinit', or 'cancel'.
    """
    stats = _gather_existing_stats(musonius_dir)

    # Build stats table
    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 1))
    table.add_column("label", style="dim", width=20)
    table.add_column("value")

    table.add_row("Last initialized", f"[cyan]{stats['last_init']}[/cyan]")
    table.add_row("Index cache", f"{stats['files_indexed']} files")

    memory_total = int(stats["decisions"]) + int(stats["conventions"]) + int(stats["failures"])
    memory_detail = (
        f"{stats['decisions']}D / {stats['conventions']}C / {stats['failures']}F"
    )
    table.add_row("Memory", f"{memory_total} entries [dim]({memory_detail})[/dim]")
    table.add_row("Epics", str(stats["epics"]))

    panel = Panel(
        table,
        title=f"[bold yellow]Existing project[/bold yellow]  [dim]{project_root.name}[/dim]",
        border_style="yellow",
        padding=(1, 2),
    )
    console.print(panel)

    # Offer choices
    console.print()
    console.print("  [bold]1.[/bold] Update — re-index codebase, keep memory & epics")
    console.print("  [bold]2.[/bold] Full re-init — wipe index & memory, start fresh")
    console.print("  [bold]3.[/bold] Cancel")
    console.print()

    choice = typer.prompt("Choose", default="1", show_default=True)
    choice = choice.strip()

    if choice == "1":
        return "update"
    elif choice == "2":
        return "reinit"
    else:
        return "cancel"


# ---------------------------------------------------------------------------
# Init command
# ---------------------------------------------------------------------------


@handle_errors
def init_command(
    auto: bool = typer.Option(False, "--auto", "-a", help="Skip interactive prompts."),
    language: str | None = typer.Option(None, "--language", "-l", help="Primary project language."),
    force: bool = typer.Option(False, "--force", "-f", help="Full re-init without prompting."),
) -> None:
    """Initialize Musonius for the current project.

    Creates the .musonius/ directory structure, indexes the codebase,
    and detects project conventions.
    """
    project_root = find_project_root()
    musonius_dir = project_root / MUSONIUS_DIR

    wipe_memory = False

    if musonius_dir.exists():
        if force:
            wipe_memory = True
        elif auto:
            # Auto mode defaults to update (non-destructive)
            pass
        else:
            action = _show_existing_project(musonius_dir, project_root)
            if action == "cancel":
                console.print("[dim]No changes made.[/dim]")
                raise typer.Exit()
            elif action == "reinit":
                wipe_memory = True
    else:
        console.print(
            Panel(
                f"Initializing [bold]{project_root.name}[/bold]",
                border_style="blue",
                padding=(0, 2),
            )
        )

    # Tracking variables
    file_count = 0
    symbol_count = 0
    convention_count = 0
    detected_tools: list[str] = []

    with PipelineProgress() as pipeline:
        # ── Step 1: Directory structure ──
        with pipeline.step("Create directory structure") as step:
            _create_directory_structure(musonius_dir)
            step.detail("6 directories")

        # ── Step 2: Wipe memory if full reinit ──
        if wipe_memory:
            with pipeline.step("Reset memory store") as step:
                db_path = musonius_dir / MEMORY_DIR / "decisions.db"
                if db_path.exists():
                    db_path.unlink()
                step.detail("Cleared")

        # ── Step 3: Configuration ──
        with pipeline.step("Write configuration") as step:
            config = load_config(project_root)
            if language:
                config["project"]["language"] = language
            save_config(project_root, config)
            step.detail(f"language={config['project'].get('language', 'python')}")

        # ── Step 4: Index codebase ──
        with pipeline.step("Index codebase") as step:
            try:
                from musonius.context.indexer import Indexer

                step.detail("Parsing with tree-sitter...")
                indexer = Indexer(project_root)
                graph = indexer.index_codebase()
                file_count = graph.file_count
                symbol_count = graph.symbol_count

                step.detail("Saving cache...")
                cache_dir = musonius_dir / INDEX_DIR
                indexer.save_cache(graph, cache_dir)

                step.detail(f"{file_count} files, {symbol_count} symbols")
            except Exception as e:
                logger.warning("Indexing failed: %s", e)
                step.detail(f"Skipped: {e}")

        # ── Step 5: Memory store ──
        store = None
        with pipeline.step("Initialize memory store") as step:
            try:
                from musonius.memory.store import MemoryStore

                store = MemoryStore(musonius_dir / MEMORY_DIR / "decisions.db")
                store.initialize()
                step.detail("SQLite ready")
            except Exception as e:
                logger.warning("Memory initialization failed: %s", e)
                step.detail(f"Skipped: {e}")

        # ── Step 6: Detect conventions ──
        with pipeline.step("Detect coding conventions") as step:
            try:
                from musonius.memory.convention_detector import (
                    detect_conventions,
                    store_conventions,
                )

                step.detail("Scanning patterns...")
                report = detect_conventions(
                    project_root,
                    graph=graph if "graph" in dir() else None,
                )
                if store is not None:
                    convention_count = store_conventions(report, store)
                step.detail(
                    f"{len(report.conventions)} found, {convention_count} stored"
                )
            except Exception as e:
                logger.warning("Convention detection failed: %s", e)
                step.detail(f"Skipped: {e}")

        # ── Step 7: Auto-configure model routing ──
        with pipeline.step("Configure model routing") as step:
            try:
                from musonius.config.defaults import generate_optimal_models
                from musonius.orchestration.cli_backend import detect_cli_tools

                step.detail("Detecting CLI tools...")
                tools = detect_cli_tools()
                detected_tools = list(tools.keys())
                optimal_models = generate_optimal_models(tools)
                config["models"] = optimal_models
                save_config(project_root, config)

                if detected_tools:
                    step.detail(f"{', '.join(detected_tools)} → auto-configured")
                else:
                    step.detail("No CLI tools found")
            except Exception as e:
                logger.warning("Model auto-config failed: %s", e)
                step.detail(f"Skipped: {e}")

    # ── Log activity ──
    try:
        from musonius.memory.activity import track_activity

        with track_activity(project_root, "init") as activity:
            activity["outcome"] = (
                f"Indexed {file_count} files, {symbol_count} symbols, "
                f"{convention_count} conventions"
            )
    except Exception:
        pass

    # ── Summary panel ──
    _print_summary(
        project_root=project_root,
        file_count=file_count,
        symbol_count=symbol_count,
        convention_count=convention_count,
        detected_tools=detected_tools,
    )


# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------


def _print_summary(
    *,
    project_root: Path,
    file_count: int,
    symbol_count: int,
    convention_count: int,
    detected_tools: list[str],
) -> None:
    """Print a polished initialization summary panel."""
    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 1))
    table.add_column("label", style="dim", width=20)
    table.add_column("value")

    table.add_row("Files indexed", f"[green]{file_count}[/green]")
    table.add_row("Symbols found", f"[green]{symbol_count}[/green]")
    table.add_row("Conventions", f"[green]{convention_count}[/green]")

    if detected_tools:
        tool_str = ", ".join(f"[green]{t}[/green]" for t in detected_tools)
        table.add_row("CLI tools", tool_str)
        table.add_row("Models", f"[dim]auto-configured for {'/'.join(detected_tools)}[/dim]")
    else:
        table.add_row("CLI tools", "[yellow]none detected[/yellow]")
        table.add_row("", "[dim]Install claude or gemini CLI for best results[/dim]")

    panel = Panel(
        table,
        title="[bold green]Musonius initialized[/bold green]",
        border_style="green",
        padding=(1, 2),
    )
    console.print(panel)

    # Next steps
    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print(f"  musonius plan [cyan]\"your task\"[/cyan]     Generate a phased plan")
    console.print(f"  musonius go [cyan]\"your task\"[/cyan]       Plan + prep in one shot")
    console.print(f"  musonius status                Show project dashboard")
    console.print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
