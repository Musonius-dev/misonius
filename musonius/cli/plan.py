"""musonius plan — generate a phased implementation plan."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from musonius.cli.display import StreamingDisplay
from musonius.cli.utils import console, handle_errors, require_initialized

if TYPE_CHECKING:
    from musonius.orchestration.router import ModelRouter

logger = logging.getLogger(__name__)


@handle_errors
def plan_command(
    task: str = typer.Argument(..., help="Task description to plan."),
    phases: int = typer.Option(1, "--phases", "-p", help="Maximum number of phases."),
    clarify: bool = typer.Option(True, "--clarify/--no-clarify", help="Ask clarifying questions."),
    agent: str = typer.Option("claude", "--agent", "-a", help="Target agent for context."),
    from_issue: str | None = typer.Option(
        None, "--from-issue", help="GitHub issue URL or number to import as task."
    ),
) -> None:
    """Generate a phased implementation plan for a task.

    Decomposes the task into file-level phases with acceptance criteria.
    """
    project_root = require_initialized()

    # Import task from GitHub issue if specified
    if from_issue:
        task = _import_issue(from_issue, project_root) or task

    console.print(Panel(task, title="Task", border_style="blue"))

    # Set up shared infrastructure
    from musonius.config.loader import load_config
    from musonius.memory.store import MemoryStore
    from musonius.orchestration.router import ModelRouter

    config = load_config(project_root)
    memory = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    memory.initialize()
    router = ModelRouter(config)

    # Intent clarification
    refined_task = task
    if clarify:
        refined_task = _run_clarification(task, router)

    # Generate plan with repo map context
    from musonius.memory.activity import track_activity

    with track_activity(project_root, "plan", args=task) as activity:
        try:
            from musonius.config.defaults import INDEX_DIR
            from musonius.context.indexer import Indexer
            from musonius.context.repo_map import RepoMapGenerator
            from musonius.planning.engine import PlanningEngine

            with StreamingDisplay("Generating plan...", transient=False) as display:
                # Load repo map from index cache
                repo_map = ""
                display.update("Loading repo map...")
                try:
                    indexer = Indexer(project_root)
                    cache_dir = project_root / ".musonius" / INDEX_DIR
                    cached_graph = indexer.load_cache(cache_dir)
                    if cached_graph:
                        repo_map_gen = RepoMapGenerator(indexer)
                        repo_map = repo_map_gen.generate(level=1, token_budget=4000)
                        display.update(f"Loaded repo map ({len(repo_map):,} chars)")
                    else:
                        display.update("No index cache, planning without repo map")
                except Exception as e:
                    logger.debug("Failed to load repo map: %s", e)
                    display.update("Repo map unavailable")

                # Generate the plan via LLM — with live status updates
                display.update("Calling LLM for plan generation...")
                engine = PlanningEngine(memory=memory, router=router, project_root=project_root)
                plan = engine.generate_plan(
                    refined_task,
                    max_phases=phases,
                    repo_map=repo_map,
                    on_status=display.update,
                )
                display.complete(
                    f"Plan generated: {plan.epic_id} ({len(plan.phases)} phases)"
                )

            # Track epic lifecycle
            memory.set_epic_status(plan.epic_id, "planned", task_description=refined_task)
            activity["epic_id"] = plan.epic_id
            activity["outcome"] = f"Generated {len(plan.phases)} phases as {plan.epic_id}"

            _display_plan(plan)
        except Exception as e:
            logger.exception("Plan generation failed")
            activity["outcome"] = f"Failed: {e}"
            console.print(f"[red]Plan generation failed:[/red] {e}")
            console.print("[dim]Tip: Run 'musonius doctor' to check your setup.[/dim]")


def _run_clarification(task: str, router: ModelRouter) -> str:
    """Run the interactive clarification flow using the IntentEngine.

    Generates questions via the scout model, presents them to the user,
    collects answers, and returns the refined task summary.

    Args:
        task: Original task description.
        router: Model router for scout calls.

    Returns:
        Refined task description incorporating clarification answers.
    """
    from musonius.intent.engine import IntentEngine

    intent_engine = IntentEngine(router=router)
    intent = intent_engine.capture_intent(task)

    console.print("\n[bold]Generating clarifying questions...[/bold]")
    try:
        questions = intent_engine.ask_clarifying_questions(task)
    except Exception as e:
        logger.debug("Question generation failed: %s", e)
        console.print("[dim]Could not generate questions, proceeding with task as-is.[/dim]\n")
        return task

    if not questions:
        console.print("[dim]No clarifying questions needed.[/dim]\n")
        return task

    # Display questions and collect answers
    console.print(f"\n[bold]Please answer {len(questions)} clarifying questions:[/bold]")
    console.print("[dim]Press Enter to skip a question.[/dim]\n")

    answers: dict[str, str] = {}
    for i, q in enumerate(questions, 1):
        console.print(f"  [bold cyan]{i}.[/bold cyan] [bold]{q.question}[/bold]")
        console.print(f"     [dim]({q.why_asking})[/dim]")
        answer = Prompt.ask("     Answer", default="", console=console)
        if answer.strip():
            answers[q.id] = answer.strip()
        console.print()

    if not answers:
        console.print("[dim]No answers provided, proceeding with original task.[/dim]\n")
        return task

    # Persist clarification Q&A for session context
    try:
        from musonius.cli.utils import find_project_root
        from musonius.memory.activity import save_clarification

        project_root = find_project_root()
        for q in questions:
            if q.id in answers:
                save_clarification(project_root, q.question, answers[q.id])
    except Exception:
        pass  # Clarification saving is non-critical

    # Refine the intent
    refined = intent_engine.refine_intent(intent, answers, questions)

    # Show validation warnings
    warnings = intent_engine.validate_intent(refined)
    if warnings:
        console.print("[dim]Intent validation notes:[/dim]")
        for w in warnings:
            console.print(f"  [dim]- {w}[/dim]")
        console.print()

    # Return the refined summary for the planning engine
    summary = refined.summary()
    console.print(Panel(summary, title="Refined Intent", border_style="green"))
    return summary


def _display_plan(plan: object) -> None:
    """Display a plan using Rich Markdown rendering.

    Uses the enhanced display module for styled terminal markdown
    with syntax-highlighted tables and acceptance criteria.
    """
    try:
        from musonius.cli.display import render_plan_markdown

        render_plan_markdown(plan)
    except Exception:
        # Fallback to basic display if enhanced rendering fails
        _display_plan_fallback(plan)


def _display_plan_fallback(plan: object) -> None:
    """Fallback plan display using basic Rich tables."""
    from musonius.planning.schemas import Plan

    if not isinstance(plan, Plan):
        console.print("[yellow]Unexpected plan format[/yellow]")
        return

    console.print(f"\n[bold green]Plan: {plan.epic_id}[/bold green]")
    console.print(f"Task: {plan.task_description}\n")

    for phase in plan.phases:
        table = Table(title=f"Phase: {phase.title}", show_header=True)
        table.add_column("File", style="cyan")
        table.add_column("Action", style="yellow")
        table.add_column("Description")

        for fc in phase.files:
            table.add_row(str(fc.path), fc.action, fc.description)

        console.print(table)

        if phase.acceptance_criteria:
            console.print("\n[bold]Acceptance Criteria:[/bold]")
            for criterion in phase.acceptance_criteria:
                console.print(f"  - [ ] {criterion}")
        console.print()


def _import_issue(issue_ref: str, project_root: Path) -> str | None:
    """Import a GitHub issue title and body as a task description.

    Args:
        issue_ref: GitHub issue URL or number.
        project_root: Project root for running git commands.

    Returns:
        Task description string, or None on failure.
    """
    import subprocess

    # Try using gh CLI for issue retrieval
    issue_id = issue_ref.strip().lstrip("#")
    if "/" in issue_id and "github.com" in issue_id:
        # Full URL — extract owner/repo#number
        cmd = ["gh", "issue", "view", issue_id, "--json", "title,body"]
    else:
        cmd = ["gh", "issue", "view", issue_id, "--json", "title,body"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            check=True,
        )
        import json

        data = json.loads(result.stdout)
        title = data.get("title", "")
        body = data.get("body", "")
        task = title
        if body:
            task = f"{title}\n\n{body}"
        console.print(f"[green]Imported issue:[/green] {title}")
        return task
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        logger.debug("Failed to import issue %s: %s", issue_ref, e)
        console.print(f"[yellow]Could not import issue:[/yellow] {e}")
        console.print("[dim]Ensure 'gh' CLI is installed and authenticated.[/dim]")
        return None
