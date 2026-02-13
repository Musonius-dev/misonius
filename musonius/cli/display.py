"""Enhanced display module — Live streaming, Markdown rendering, status bar.

Provides the UX layer that sits between Musonius commands and the terminal:

- StreamingDisplay: Rich Live context manager for LLM/long operations
- render_plan_markdown: Render plan output as styled terminal markdown
- render_verification_markdown: Render verification results with severity coloring
- StatusBar: Persistent footer showing epic/phase/tokens/memory stats
- PipelineProgress: Multi-step progress tracker for go command pipeline
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from musonius.cli.utils import console

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Streaming Live Display
# ---------------------------------------------------------------------------


class StreamingDisplay:
    """Rich Live display for long-running operations.

    Shows an animated spinner with operation status, elapsed time,
    and optional detail text that updates in-place.

    Usage:
        with StreamingDisplay("Generating plan...") as display:
            display.update("Analyzing codebase structure...")
            result = slow_operation()
            display.update("Building phase breakdown...")
            more_work()
            display.complete("Plan generated (3 phases)")
    """

    def __init__(
        self,
        title: str,
        *,
        show_elapsed: bool = True,
        transient: bool = True,
    ) -> None:
        """Initialize the streaming display.

        Args:
            title: Initial status message.
            show_elapsed: Show elapsed time counter.
            transient: Clear display when done (vs leave final state).
        """
        self._title = title
        self._detail = ""
        self._show_elapsed = show_elapsed
        self._transient = transient
        self._start_time = 0.0
        self._live: Live | None = None
        self._completed = False
        self._final_message = ""

    def _build_display(self) -> Panel:
        """Build the current display panel."""
        parts: list[str] = []

        if not self._completed:
            parts.append(f"[bold cyan]⠋[/bold cyan] {self._title}")
        else:
            parts.append(f"[bold green]✓[/bold green] {self._final_message or self._title}")

        if self._detail and not self._completed:
            parts.append(f"  [dim]{self._detail}[/dim]")

        if self._show_elapsed and not self._completed:
            elapsed = time.monotonic() - self._start_time
            parts.append(f"  [dim]{elapsed:.1f}s[/dim]")

        text = "\n".join(parts)
        return Panel(text, border_style="blue" if not self._completed else "green", padding=(0, 1))

    def update(self, detail: str) -> None:
        """Update the detail text shown under the spinner.

        Args:
            detail: New detail message.
        """
        self._detail = detail
        if self._live:
            self._live.update(self._build_display())

    def update_title(self, title: str) -> None:
        """Update the main title text.

        Args:
            title: New title message.
        """
        self._title = title
        if self._live:
            self._live.update(self._build_display())

    def complete(self, message: str = "") -> None:
        """Mark the operation as complete.

        Args:
            message: Final success message (defaults to title).
        """
        self._completed = True
        self._final_message = message or self._title
        if self._live:
            self._live.update(self._build_display())

    def __enter__(self) -> StreamingDisplay:
        self._start_time = time.monotonic()
        self._live = Live(
            self._build_display(),
            console=console,
            transient=self._transient,
            refresh_per_second=8,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._live:
            if not self._completed:
                self.complete()
            self._live.__exit__(*args)
            self._live = None


# ---------------------------------------------------------------------------
# Pipeline Progress (multi-step)
# ---------------------------------------------------------------------------


class PipelineProgress:
    """Multi-step progress tracker for pipeline commands like `go`.

    Shows each step with status indicators, elapsed time,
    and an overall progress bar.

    Usage:
        with PipelineProgress() as pipeline:
            with pipeline.step("Indexing codebase") as step:
                index()
                step.detail("Found 342 files")
            with pipeline.step("Generating plan") as step:
                plan = generate()
                step.detail(f"{len(plan.phases)} phases")
            with pipeline.step("Writing handoff") as step:
                write_handoff()
    """

    def __init__(self) -> None:
        self._steps: list[dict[str, Any]] = []
        self._current_step: int = -1
        self._live: Live | None = None
        self._start_time = 0.0

    def _build_display(self) -> Table:
        """Build the pipeline progress table."""
        table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("icon", width=3, no_wrap=True)
        table.add_column("step", ratio=3)
        table.add_column("detail", ratio=2, style="dim")
        table.add_column("time", width=8, justify="right", style="dim")

        for i, step in enumerate(self._steps):
            if step["status"] == "completed":
                icon = "[bold green]✓[/bold green]"
                style = ""
            elif step["status"] == "running":
                icon = "[bold cyan]⠋[/bold cyan]"
                style = "bold"
            elif step["status"] == "failed":
                icon = "[bold red]✗[/bold red]"
                style = "red"
            else:
                icon = "[dim]○[/dim]"
                style = "dim"

            elapsed_str = ""
            if step.get("elapsed"):
                elapsed_str = f"{step['elapsed']:.1f}s"
            elif step["status"] == "running":
                elapsed_str = f"{time.monotonic() - step['start_time']:.1f}s"

            table.add_row(
                icon,
                Text(step["name"], style=style),
                step.get("detail", ""),
                elapsed_str,
            )

        return table

    @contextmanager
    def step(self, name: str) -> Generator[_StepHandle, None, None]:
        """Start a pipeline step.

        Args:
            name: Step description.

        Yields:
            StepHandle for updating detail text.
        """
        step_data: dict[str, Any] = {
            "name": name,
            "status": "running",
            "detail": "",
            "start_time": time.monotonic(),
            "elapsed": None,
        }
        self._steps.append(step_data)
        self._current_step = len(self._steps) - 1
        handle = _StepHandle(step_data, self)

        if self._live:
            self._live.update(self._build_display())

        try:
            yield handle
            step_data["status"] = "completed"
        except Exception:
            step_data["status"] = "failed"
            raise
        finally:
            step_data["elapsed"] = time.monotonic() - step_data["start_time"]
            if self._live:
                self._live.update(self._build_display())

    def _refresh(self) -> None:
        """Refresh the live display."""
        if self._live:
            self._live.update(self._build_display())

    def __enter__(self) -> PipelineProgress:
        self._start_time = time.monotonic()
        self._live = Live(
            self._build_display(),
            console=console,
            refresh_per_second=8,
            transient=False,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._live:
            self._live.update(self._build_display())
            self._live.__exit__(*args)
            self._live = None

        # Print total elapsed
        total = time.monotonic() - self._start_time
        console.print(f"\n[dim]Total: {total:.1f}s[/dim]")


class _StepHandle:
    """Handle for updating a pipeline step's detail text."""

    def __init__(self, step_data: dict[str, Any], pipeline: PipelineProgress) -> None:
        self._data = step_data
        self._pipeline = pipeline

    def detail(self, text: str) -> None:
        """Update the step's detail text."""
        self._data["detail"] = text
        self._pipeline._refresh()


# ---------------------------------------------------------------------------
# Markdown Rendering
# ---------------------------------------------------------------------------


def render_plan_markdown(plan: Any) -> None:
    """Render a Plan as styled terminal markdown with syntax-highlighted code.

    Shows the plan with phase headers, file tables, and acceptance criteria
    formatted as Rich Markdown for a polished terminal experience.

    Args:
        plan: A Plan object from musonius.planning.schemas.
    """
    from musonius.planning.schemas import Plan

    if not isinstance(plan, Plan):
        console.print("[yellow]Unexpected plan format[/yellow]")
        return

    # Build markdown string
    md_parts: list[str] = []
    md_parts.append(f"# {plan.epic_id}")
    md_parts.append(f"\n**Task:** {plan.task_description}\n")

    for i, phase in enumerate(plan.phases, 1):
        md_parts.append(f"## Phase {i}: {phase.title}\n")

        if phase.files:
            md_parts.append("| File | Action | Description |")
            md_parts.append("|------|--------|-------------|")
            for fc in phase.files:
                md_parts.append(f"| `{fc.path}` | {fc.action} | {fc.description} |")
            md_parts.append("")

        if phase.acceptance_criteria:
            md_parts.append("**Acceptance Criteria:**\n")
            for criterion in phase.acceptance_criteria:
                md_parts.append(f"- [ ] {criterion}")
            md_parts.append("")

    markdown_text = "\n".join(md_parts)

    # Render with Rich Markdown
    panel = Panel(
        Markdown(markdown_text),
        title=f"[bold green]{plan.epic_id}[/bold green]",
        border_style="green",
        padding=(1, 2),
    )
    console.print(panel)


def render_verification_markdown(result: Any) -> None:
    """Render verification results as styled markdown with severity coloring.

    Uses Rich Tree + Markdown for a polished terminal output that's
    more readable than raw text dumps.

    Args:
        result: A VerificationResult from musonius.verification.engine.
    """
    from musonius.verification.engine import VerificationResult
    from musonius.verification.severity import Severity

    if not isinstance(result, VerificationResult):
        return

    # Header
    title_parts = ["Verification Results"]
    if result.epic_id:
        title_parts.append(result.epic_id)
    if result.phase_id:
        title_parts.append(f"phase-{result.phase_id}")

    status_icon = "✓" if result.passed else "✗"
    status_color = "green" if result.passed else "red"
    status_text = "PASSED" if result.passed else "FAILED"
    header = f"[{status_color} bold]{status_icon} {status_text}[/{status_color} bold]"

    # Summary stats
    stats_parts: list[str] = []
    if result.critical_count:
        stats_parts.append(f"[red]{result.critical_count} critical[/red]")
    if result.major_count:
        stats_parts.append(f"[yellow]{result.major_count} major[/yellow]")
    if result.minor_count:
        stats_parts.append(f"[cyan]{result.minor_count} minor[/cyan]")
    if result.outdated_count:
        stats_parts.append(f"[dim]{result.outdated_count} outdated[/dim]")
    stats_line = " / ".join(stats_parts) if stats_parts else "[green]Clean[/green]"

    # Build content
    content_parts: list[Any] = []
    content_parts.append(Text.from_markup(f"{header}  {stats_line}"))

    if result.diff_summary:
        content_parts.append(Text.from_markup(f"\n[dim]{result.diff_summary}[/dim]"))

    # Findings tree
    if result.findings:
        content_parts.append(Text(""))
        tree = _build_findings_tree(result)
        content_parts.append(tree)

    # Fix suggestions
    if result.fix_suggestions:
        content_parts.append(Text(""))
        fix_table = Table(title="Suggested Fixes", show_header=True, title_style="bold")
        fix_table.add_column("#", width=4, style="bold")
        fix_table.add_column("Fix")
        fix_table.add_column("Confidence", width=12, justify="right")

        for i, fix in enumerate(result.fix_suggestions, 1):
            conf_bar = _confidence_bar(fix.confidence)
            fix_table.add_row(str(i), fix.description, conf_bar)

        content_parts.append(fix_table)

    panel = Panel(
        Group(*content_parts),
        title=" / ".join(title_parts),
        border_style=status_color,
        padding=(1, 2),
    )
    console.print(panel)


def _build_findings_tree(result: Any) -> Tree:
    """Build a severity-grouped findings tree."""
    from musonius.verification.severity import Severity

    severity_config = [
        (Severity.CRITICAL, "red", "CRITICAL"),
        (Severity.MAJOR, "yellow", "MAJOR"),
        (Severity.MINOR, "cyan", "MINOR"),
        (Severity.OUTDATED, "dim", "OUTDATED"),
        (Severity.INFO, "dim", "INFO"),
    ]

    root = Tree("[bold]Findings[/bold]")

    for sev, color, label in severity_config:
        findings = [f for f in result.findings if f.severity == sev]
        if not findings:
            continue

        branch = root.add(f"[{color} bold]{label}[/{color} bold] ({len(findings)})")
        for finding in findings:
            loc = finding.file_path or ""
            if finding.line_number:
                loc += f":{finding.line_number}"

            if loc:
                leaf = branch.add(f"[{color}]{loc}[/{color}]")
            else:
                leaf = branch

            leaf.add(f"[dim]{finding.message}[/dim]")
            if finding.plan_reference:
                leaf.add(f"[dim italic]↳ Plan: {finding.plan_reference}[/dim italic]")

    return root


def _confidence_bar(confidence: float) -> str:
    """Render a confidence value as a colored percentage."""
    pct = int(confidence * 100)
    if pct >= 80:
        return f"[green]{pct}%[/green]"
    elif pct >= 50:
        return f"[yellow]{pct}%[/yellow]"
    else:
        return f"[red]{pct}%[/red]"


# ---------------------------------------------------------------------------
# Status Bar
# ---------------------------------------------------------------------------


class StatusBar:
    """Persistent status footer showing project state.

    Displays: current epic, phase progress, token budget used,
    memory entry counts, and CLI tool availability.

    Usage:
        bar = StatusBar(project_root)
        bar.print()  # One-shot print

        # Or use with Live for persistent display:
        with bar.live():
            do_work()
            bar.refresh()
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize status bar with project root.

        Args:
            project_root: Path to project root containing .musonius/.
        """
        self._project_root = project_root
        self._musonius_dir = project_root / ".musonius"

    def _gather_stats(self) -> dict[str, Any]:
        """Gather current project statistics."""
        stats: dict[str, Any] = {
            "project": self._project_root.name,
            "epic": None,
            "phase_progress": "",
            "memory_decisions": 0,
            "memory_conventions": 0,
            "memory_failures": 0,
            "index_files": 0,
            "cli_tools": [],
        }

        # Check index
        index_dir = self._musonius_dir / "index"
        if index_dir.exists():
            stats["index_files"] = len(list(index_dir.glob("*")))

        # Check memory
        db_path = self._musonius_dir / "memory" / "decisions.db"
        if db_path.exists():
            try:
                from musonius.memory.store import MemoryStore

                store = MemoryStore(db_path)
                store.initialize()
                stats["memory_decisions"] = len(store.get_all_decisions())
                stats["memory_conventions"] = len(store.get_all_conventions())
                stats["memory_failures"] = len(store.get_all_failures())
                store.close()
            except Exception:
                pass

        # Check latest epic
        epics_dir = self._musonius_dir / "epics"
        if epics_dir.exists():
            epic_dirs = sorted(
                [d for d in epics_dir.iterdir() if d.is_dir()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            if epic_dirs:
                latest = epic_dirs[0]
                stats["epic"] = latest.name
                phases_dir = latest / "phases"
                if phases_dir.exists():
                    total_phases = len(list(phases_dir.glob("phase-*.md")))
                    stats["phase_progress"] = f"{total_phases} phases"

        # Check CLI tools
        try:
            from musonius.orchestration.cli_backend import detect_cli_tools

            tools = detect_cli_tools()
            stats["cli_tools"] = list(tools.keys())
        except Exception:
            pass

        return stats

    def build(self) -> Table:
        """Build the status bar as a Rich Table.

        Returns:
            Rich Table with single-row status display.
        """
        stats = self._gather_stats()

        table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("section", ratio=1)
        table.add_column("section", ratio=1)
        table.add_column("section", ratio=1)
        table.add_column("section", ratio=1)

        # Column 1: Project + Epic
        epic_text = f"[cyan]{stats['epic']}[/cyan]" if stats["epic"] else "[dim]no epic[/dim]"
        col1 = f"[bold]{stats['project']}[/bold] → {epic_text}"
        if stats["phase_progress"]:
            col1 += f" ({stats['phase_progress']})"

        # Column 2: Memory
        mem_total = stats["memory_decisions"] + stats["memory_conventions"] + stats["memory_failures"]
        col2 = f"Memory: [green]{mem_total}[/green] entries"

        # Column 3: Index
        col3 = f"Index: [green]{stats['index_files']}[/green] files"

        # Column 4: CLI tools
        if stats["cli_tools"]:
            tool_str = ", ".join(f"[green]{t}[/green]" for t in stats["cli_tools"])
            col4 = f"CLI: {tool_str}"
        else:
            col4 = "CLI: [dim]none[/dim]"

        table.add_row(col1, col2, col3, col4)

        return Panel(table, border_style="dim", padding=(0, 0))

    def print(self) -> None:
        """Print the status bar once."""
        console.print(self.build())

    @contextmanager
    def live(self) -> Generator[StatusBar, None, None]:
        """Show the status bar as a persistent live display.

        Yields:
            Self, for calling refresh() during operations.
        """
        with Live(self.build(), console=console, refresh_per_second=2) as live:
            self._live = live
            try:
                yield self
            finally:
                self._live = None

    def refresh(self) -> None:
        """Refresh the live status bar with current stats."""
        if hasattr(self, "_live") and self._live:
            self._live.update(self.build())


# ---------------------------------------------------------------------------
# Enhanced Status Command Display
# ---------------------------------------------------------------------------


def render_status_dashboard(project_root: Path) -> None:
    """Render a full-featured status dashboard.

    More comprehensive than the basic status command — includes
    CLI tool detection, model routing info, and epic lifecycle.

    Args:
        project_root: Project root path.
    """
    musonius_dir = project_root / ".musonius"

    # Header
    console.print(
        Panel(
            f"[bold]{project_root.name}[/bold]",
            title="[bold]Musonius Status[/bold]",
            border_style="blue",
            padding=(0, 2),
        )
    )

    # Build three-column layout
    # Left: Project Components
    components = Table(title="Components", show_header=True, title_style="bold")
    components.add_column("Component", style="cyan")
    components.add_column("Status")
    components.add_column("Details", style="dim")

    # Index
    index_dir = musonius_dir / "index"
    if index_dir.exists():
        count = len(list(index_dir.glob("*")))
        components.add_row("Index", "[green]●[/green] Built", f"{count} cached")
    else:
        components.add_row("Index", "[red]○[/red] Missing", "Run init")

    # Memory
    db_path = musonius_dir / "memory" / "decisions.db"
    if db_path.exists():
        try:
            from musonius.memory.store import MemoryStore

            store = MemoryStore(db_path)
            store.initialize()
            d = len(store.get_all_decisions())
            c = len(store.get_all_conventions())
            f = len(store.get_all_failures())
            components.add_row("Memory", "[green]●[/green] Active", f"{d}D {c}C {f}F")
            store.close()
        except Exception:
            components.add_row("Memory", "[yellow]●[/yellow] Error", "DB issue")
    else:
        components.add_row("Memory", "[red]○[/red] Empty", "Run init")

    # Config
    config_path = musonius_dir / "config.yaml"
    if config_path.exists():
        components.add_row("Config", "[green]●[/green] Found", str(config_path.relative_to(project_root)))
    else:
        components.add_row("Config", "[red]○[/red] Missing", "")

    # CLI Tools
    try:
        from musonius.orchestration.cli_backend import detect_cli_tools

        tools = detect_cli_tools()
        if tools:
            tool_names = ", ".join(tools.keys())
            components.add_row("CLI Tools", "[green]●[/green] Available", tool_names)
        else:
            components.add_row("CLI Tools", "[yellow]○[/yellow] None", "Install claude/gemini CLI")
    except Exception:
        components.add_row("CLI Tools", "[dim]○[/dim] Unknown", "")

    console.print(components)

    # Model routing
    if config_path.exists():
        try:
            from musonius.config.loader import load_config

            config = load_config(project_root)
            models = config.get("models", {})

            routing = Table(title="Model Routing", show_header=True, title_style="bold")
            routing.add_column("Role", style="cyan")
            routing.add_column("Model")
            routing.add_column("Strategy", style="dim")

            for role in ["scout", "planner", "implementer", "verifier", "summarizer"]:
                model = models.get(role, "[dim]default[/dim]")
                # Determine strategy
                strategy = _detect_strategy(model)
                routing.add_row(role, str(model), strategy)

            console.print(routing)
        except Exception:
            pass

    # Epic progress
    epics_dir = musonius_dir / "epics"
    if epics_dir.exists():
        epic_dirs = sorted(
            [d for d in epics_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if epic_dirs:
            epics_table = Table(title="Epics", show_header=True, title_style="bold")
            epics_table.add_column("Epic", style="cyan")
            epics_table.add_column("Phases", justify="center")
            epics_table.add_column("Task")

            for epic_dir in epic_dirs[:10]:  # Show latest 10
                phases_dir = epic_dir / "phases"
                phase_count = len(list(phases_dir.glob("phase-*.md"))) if phases_dir.exists() else 0

                spec = epic_dir / "spec.md"
                task_desc = ""
                if spec.exists():
                    first = spec.read_text().split("\n")[0]
                    task_desc = first.lstrip("# ").strip()

                epics_table.add_row(
                    epic_dir.name,
                    str(phase_count),
                    task_desc[:50] + ("..." if len(task_desc) > 50 else ""),
                )

            console.print(epics_table)

    # Status bar at bottom
    bar = StatusBar(project_root)
    bar.print()


def _detect_strategy(model: Any) -> str:
    """Detect which routing strategy will be used for a model."""
    import os

    if not isinstance(model, str):
        return ""

    provider_keys = {
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "google": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
    }

    # Check if it's a provider-prefixed model
    for prefix, env_var in provider_keys.items():
        if model.startswith(f"{prefix}/"):
            if os.environ.get(env_var):
                return "API key"
            # Check CLI
            try:
                from musonius.orchestration.cli_backend import detect_cli_tools

                tools = detect_cli_tools()
                cli_map = {"anthropic": "claude", "gemini": "gemini", "google": "gemini"}
                if cli_map.get(prefix) in tools:
                    return "CLI tool"
            except Exception:
                pass
            return "[red]No route[/red]"

    if model.startswith("ollama/"):
        return "Local"

    return "Auto"
