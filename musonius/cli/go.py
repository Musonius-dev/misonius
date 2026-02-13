"""musonius go — one-command flow: init → plan → prep in one shot."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from musonius.cli.utils import console, handle_errors

logger = logging.getLogger(__name__)


@handle_errors
def go_command(
    task: str = typer.Argument(..., help="Task description."),
    agent: str = typer.Option("claude", "--agent", "-a", help="Target agent for handoff."),
    phases: int = typer.Option(1, "--phases", "-p", help="Maximum number of phases."),
    output: str | None = typer.Option(None, "--output", "-o", help="Custom output path."),
    skip_init: bool = typer.Option(False, "--skip-init", help="Skip init if already initialized."),
) -> None:
    """One-command flow: init → plan → prep.

    Automatically detects what's already done and skips accordingly.
    Produces a ready-to-use handoff file for your coding agent.
    """
    console.print(Panel(task, title="Task", border_style="blue"))
    project_root = Path.cwd()

    from musonius.memory.activity import track_activity

    with track_activity(project_root, "go", args=task) as activity:
        musonius_dir = project_root / ".musonius"
        already_initialized = musonius_dir.is_dir() and (musonius_dir / "config.yaml").exists()

        plan = None
        handoff_path = None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Step 1: Init (skip if already done and --skip-init or auto-detected)
            if already_initialized and skip_init:
                progress.add_task("[dim]Already initialized — skipping init.[/dim]", total=1)
            elif already_initialized:
                init_task = progress.add_task("Re-indexing codebase...", total=None)
                _run_init(project_root, progress, init_task, reindex=True)
            else:
                init_task = progress.add_task("Initializing project...", total=None)
                _run_init(project_root, progress, init_task, reindex=False)

            # Step 2: Plan
            plan_task = progress.add_task("Generating plan...", total=None)
            plan = _run_plan(project_root, task, phases, progress, plan_task)

            if not plan:
                console.print("[red]Plan generation failed. Falling back to prep-only mode.[/red]")

            # Step 3: Prep
            prep_task = progress.add_task("Generating handoff...", total=None)
            handoff_path = _run_prep(project_root, agent, output, progress, prep_task)

        # Track epic and outcome
        if plan:
            from musonius.planning.schemas import Plan

            if isinstance(plan, Plan):
                activity["epic_id"] = plan.epic_id

        parts = []
        if plan:
            from musonius.planning.schemas import Plan as PlanSchema

            if isinstance(plan, PlanSchema):
                parts.append(f"plan={plan.epic_id} ({len(plan.phases)} phases)")
        if handoff_path:
            parts.append(f"handoff={handoff_path}")
        activity["outcome"] = "go complete: " + ", ".join(parts) if parts else "go complete"

        # Display results
        console.print()
        if plan:
            from musonius.planning.schemas import Plan

            if isinstance(plan, Plan):
                console.print(f"[bold green]Plan:[/bold green] {plan.epic_id} ({len(plan.phases)} phases)")
                for phase in plan.phases:
                    console.print(f"  Phase: {phase.title} ({len(phase.files)} files)")

        if handoff_path and Path(handoff_path).exists():
            size = Path(handoff_path).stat().st_size
            console.print(f"\n[bold green]Handoff ready:[/bold green] {handoff_path} ({size:,} bytes)")
            console.print(f"\n[dim]Feed this file to your {agent} agent to start coding.[/dim]")
        else:
            console.print("[yellow]Handoff file was not generated.[/yellow]")


def _run_init(
    project_root: Path,
    progress: Progress,
    task_id: object,
    reindex: bool = False,
) -> None:
    """Run the init step."""
    try:
        from musonius.config.defaults import INDEX_DIR
        from musonius.config.loader import load_config, save_config
        from musonius.context.indexer import Indexer
        from musonius.memory.convention_detector import detect_conventions, store_conventions
        from musonius.memory.store import MemoryStore

        musonius_dir = project_root / ".musonius"

        if not musonius_dir.exists():
            # Create scaffold
            for subdir in ["index", "memory", "epics", "sot"]:
                (musonius_dir / subdir).mkdir(parents=True, exist_ok=True)

            config = load_config(project_root)
            save_config(config, musonius_dir / "config.yaml")

        # Set up memory
        db_path = musonius_dir / "memory" / "decisions.db"
        store = MemoryStore(db_path)
        store.initialize()

        # Index codebase
        indexer = Indexer(project_root)
        graph = indexer.index_codebase()
        cache_dir = musonius_dir / INDEX_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        indexer.save_cache(graph, cache_dir)

        # Detect conventions
        try:
            report = detect_conventions(project_root, graph)
            count = store_conventions(report, store)
            progress.update(
                task_id,
                description=f"Initialized ({graph.file_count} files, {count} conventions).",
            )
        except Exception:
            progress.update(
                task_id,
                description=f"Initialized ({graph.file_count} files).",
            )

        store.close()
    except Exception as e:
        logger.debug("Init failed: %s", e)
        progress.update(task_id, description=f"Init warning: {e}")


def _run_plan(
    project_root: Path,
    task: str,
    max_phases: int,
    progress: Progress,
    task_id: object,
) -> object | None:
    """Run the plan step. Returns the Plan object or None on failure."""
    try:
        from musonius.config.defaults import INDEX_DIR
        from musonius.config.loader import load_config
        from musonius.context.indexer import Indexer
        from musonius.context.repo_map import RepoMapGenerator
        from musonius.memory.store import MemoryStore
        from musonius.orchestration.router import ModelRouter
        from musonius.planning.engine import PlanningEngine

        config = load_config(project_root)
        memory = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
        memory.initialize()
        router = ModelRouter(config)

        # Load repo map
        repo_map = ""
        try:
            indexer = Indexer(project_root)
            cache_dir = project_root / ".musonius" / INDEX_DIR
            cached_graph = indexer.load_cache(cache_dir)
            if cached_graph:
                repo_map_gen = RepoMapGenerator(indexer)
                repo_map = repo_map_gen.generate(level=1, token_budget=4000)
        except Exception as e:
            logger.debug("Failed to load repo map: %s", e)

        engine = PlanningEngine(memory=memory, router=router, project_root=project_root)
        plan = engine.generate_plan(task, max_phases=max_phases, repo_map=repo_map)

        progress.update(
            task_id,
            description=f"Plan generated: {plan.epic_id} ({len(plan.phases)} phases).",
        )
        memory.close()
        return plan
    except Exception as e:
        logger.debug("Plan generation failed: %s", e)
        progress.update(task_id, description=f"Plan skipped: {e}")
        return None


def _run_prep(
    project_root: Path,
    agent: str,
    output: str | None,
    progress: Progress,
    task_id: object,
) -> str | None:
    """Run the prep step. Returns the handoff file path or None on failure."""
    try:
        from musonius.config.defaults import INDEX_DIR
        from musonius.config.loader import load_config
        from musonius.context.engine import ContextEngine
        from musonius.context.indexer import Indexer
        from musonius.context.repo_map import RepoMapGenerator
        from musonius.memory.store import MemoryStore

        config = load_config(project_root)
        memory = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
        memory.initialize()

        # Load index data
        indexer = Indexer(project_root)
        cache_dir = project_root / ".musonius" / INDEX_DIR
        cached_graph = indexer.load_cache(cache_dir)

        repo_map_gen = RepoMapGenerator(indexer)

        # Generate handoff via ContextEngine
        engine = ContextEngine(
            project_root=project_root,
            indexer=indexer,
            repo_map_generator=repo_map_gen,
            memory_store=memory,
        )

        result = engine.get_context(
            task="",  # Task already captured in the plan
            agent=agent,
        )
        handoff = result.formatted_output

        # Determine output path
        if output:
            out_path = output
        else:
            out_path = str(project_root / "HANDOFF.md")

        Path(out_path).write_text(handoff)
        size = len(handoff)
        progress.update(task_id, description=f"Handoff written ({size:,} chars).")
        memory.close()
        return out_path
    except Exception as e:
        logger.debug("Prep failed: %s", e)
        progress.update(task_id, description=f"Prep warning: {e}")
        return None
