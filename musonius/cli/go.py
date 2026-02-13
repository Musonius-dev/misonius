"""musonius go — one-command flow: init → plan → prep in one shot."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel

from musonius.cli.display import PipelineProgress, _StepHandle, render_plan_markdown
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

        plan: Any = None
        handoff_path: str | None = None

        with PipelineProgress() as pipeline:
            # Step 1: Init
            if already_initialized and skip_init:
                with pipeline.step("Initialize") as step:
                    step.detail("Already initialized — skipped")
            elif already_initialized:
                with pipeline.step("Re-index codebase") as step:
                    _run_init_pipeline(project_root, step, reindex=True)
            else:
                with pipeline.step("Initialize project") as step:
                    _run_init_pipeline(project_root, step, reindex=False)

            # Step 2: Plan
            with pipeline.step("Generate plan") as step:
                plan = _run_plan_pipeline(project_root, task, phases, step)
                if not plan:
                    step.detail("Failed — falling back to prep-only")

            # Step 3: Prep
            with pipeline.step("Generate handoff") as step:
                handoff_path = _run_prep_pipeline(project_root, agent, output, step)

        # Track epic and outcome
        if plan:
            from musonius.planning.schemas import Plan

            if isinstance(plan, Plan):
                activity["epic_id"] = plan.epic_id

        parts: list[str] = []
        if plan:
            from musonius.planning.schemas import Plan as PlanSchema

            if isinstance(plan, PlanSchema):
                parts.append(f"plan={plan.epic_id} ({len(plan.phases)} phases)")
        if handoff_path:
            parts.append(f"handoff={handoff_path}")
        activity["outcome"] = "go complete: " + ", ".join(parts) if parts else "go complete"

        # Display results with enhanced rendering
        console.print()
        if plan:
            try:
                render_plan_markdown(plan)
            except Exception:
                from musonius.planning.schemas import Plan

                if isinstance(plan, Plan):
                    console.print(
                        f"[bold green]Plan:[/bold green] {plan.epic_id} "
                        f"({len(plan.phases)} phases)"
                    )
                    for phase in plan.phases:
                        console.print(f"  Phase: {phase.title} ({len(phase.files)} files)")

        if handoff_path and Path(handoff_path).exists():
            size = Path(handoff_path).stat().st_size
            console.print(f"\n[bold green]Handoff ready:[/bold green] {handoff_path} ({size:,} bytes)")
            console.print(f"\n[dim]Feed this file to your {agent} agent to start coding.[/dim]")
        else:
            console.print("[yellow]Handoff file was not generated.[/yellow]")


def _run_init_pipeline(
    project_root: Path,
    step: _StepHandle,
    reindex: bool = False,
) -> None:
    """Run the init step with pipeline progress tracking."""
    try:
        from musonius.config.defaults import INDEX_DIR
        from musonius.config.loader import load_config, save_config
        from musonius.context.indexer import Indexer
        from musonius.memory.convention_detector import detect_conventions, store_conventions
        from musonius.memory.store import MemoryStore

        musonius_dir = project_root / ".musonius"

        if not musonius_dir.exists():
            for subdir in ["index", "memory", "epics", "sot"]:
                (musonius_dir / subdir).mkdir(parents=True, exist_ok=True)
            config = load_config(project_root)
            save_config(project_root, config)

        db_path = musonius_dir / "memory" / "decisions.db"
        store = MemoryStore(db_path)
        store.initialize()

        step.detail("Indexing files...")
        indexer = Indexer(project_root)
        graph = indexer.index_codebase()
        cache_dir = musonius_dir / INDEX_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        indexer.save_cache(graph, cache_dir)

        try:
            step.detail("Detecting conventions...")
            report = detect_conventions(project_root, graph)
            count = store_conventions(report, store)
            step.detail(f"{graph.file_count} files, {count} conventions")
        except Exception:
            step.detail(f"{graph.file_count} files indexed")

        # Auto-configure model routing based on available CLI tools
        try:
            step.detail("Configuring models...")
            from musonius.config.defaults import generate_optimal_models

            optimal = generate_optimal_models()
            config = load_config(project_root)
            config["models"] = optimal
            save_config(project_root, config)
        except Exception:
            pass  # Auto-config is non-critical

        store.close()
    except Exception as e:
        logger.debug("Init failed: %s", e)
        step.detail(f"Warning: {e}")


def _run_plan_pipeline(
    project_root: Path,
    task: str,
    max_phases: int,
    step: _StepHandle,
) -> Any | None:
    """Run the plan step with pipeline progress tracking."""
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

        step.detail("Loading repo map...")
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

        step.detail("Calling LLM...")
        engine = PlanningEngine(memory=memory, router=router, project_root=project_root)
        plan = engine.generate_plan(
            task, max_phases=max_phases, repo_map=repo_map, on_status=step.detail,
        )

        step.detail(f"{plan.epic_id} ({len(plan.phases)} phases)")
        memory.close()
        return plan
    except Exception as e:
        logger.debug("Plan generation failed: %s", e)
        step.detail(f"Skipped: {e}")
        return None


def _run_prep_pipeline(
    project_root: Path,
    agent: str,
    output: str | None,
    step: _StepHandle,
) -> str | None:
    """Run the prep step with pipeline progress tracking."""
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

        step.detail("Loading index...")
        indexer = Indexer(project_root)
        cache_dir = project_root / ".musonius" / INDEX_DIR
        indexer.load_cache(cache_dir)

        repo_map_gen = RepoMapGenerator(indexer)

        step.detail(f"Building {agent} context...")
        engine = ContextEngine(
            project_root=project_root,
            indexer=indexer,
            repo_map_generator=repo_map_gen,
            memory_store=memory,
        )
        result = engine.get_context(task="", agent=agent)
        handoff = result.formatted_output

        if output:
            out_path = output
        else:
            out_path = str(project_root / "HANDOFF.md")

        Path(out_path).write_text(handoff)
        size = len(handoff)
        step.detail(f"{size:,} chars → {Path(out_path).name}")
        memory.close()
        return out_path
    except Exception as e:
        logger.debug("Prep failed: %s", e)
        step.detail(f"Warning: {e}")
        return None
