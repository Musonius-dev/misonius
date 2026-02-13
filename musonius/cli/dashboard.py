"""Textual TUI dashboard for musonius run.

A split-pane terminal UI that shows:
- Top: Pipeline phase progress with live status
- Center: Current operation output (plan, verification, handoff)
- Bottom: Status footer with epic/phase/tokens/memory stats

This goes beyond what a conversational CLI can show — it's a
dashboard designed for orchestrator workflows.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical
    from textual.reactive import reactive
    from textual.widget import Widget
    from textual.widgets import (
        DataTable,
        Footer,
        Header,
        Label,
        Log,
        ProgressBar,
        RichLog,
        Static,
    )

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline step data
# ---------------------------------------------------------------------------


class StepStatus:
    """Status constants for pipeline steps."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Textual Widgets
# ---------------------------------------------------------------------------


if TEXTUAL_AVAILABLE:

    class PipelineWidget(Static):
        """Displays pipeline step progress with status indicators."""

        steps: reactive[list[dict[str, Any]]] = reactive(list, always_update=True)

        def render(self) -> Table:
            """Render the pipeline as a Rich Table."""
            table = Table(
                show_header=True,
                show_edge=False,
                expand=True,
                title="Pipeline",
                title_style="bold blue",
            )
            table.add_column("", width=3)
            table.add_column("Step")
            table.add_column("Status", width=12)
            table.add_column("Detail", style="dim")
            table.add_column("Time", width=8, justify="right", style="dim")

            icons = {
                StepStatus.PENDING: "[dim]○[/dim]",
                StepStatus.RUNNING: "[bold cyan]⠋[/bold cyan]",
                StepStatus.COMPLETED: "[bold green]✓[/bold green]",
                StepStatus.FAILED: "[bold red]✗[/bold red]",
                StepStatus.SKIPPED: "[dim]–[/dim]",
            }

            status_styles = {
                StepStatus.PENDING: "dim",
                StepStatus.RUNNING: "bold cyan",
                StepStatus.COMPLETED: "green",
                StepStatus.FAILED: "red",
                StepStatus.SKIPPED: "dim",
            }

            for step in self.steps:
                status = step.get("status", StepStatus.PENDING)
                icon = icons.get(status, "?")
                style = status_styles.get(status, "")
                elapsed = ""
                if step.get("elapsed"):
                    elapsed = f"{step['elapsed']:.1f}s"
                elif status == StepStatus.RUNNING and step.get("start_time"):
                    elapsed = f"{time.monotonic() - step['start_time']:.1f}s"

                table.add_row(
                    icon,
                    Text(step.get("name", ""), style=style),
                    Text(status.capitalize(), style=style),
                    step.get("detail", ""),
                    elapsed,
                )

            return table

    class MemoryWidget(Static):
        """Shows memory and project stats."""

        stats: reactive[dict[str, Any]] = reactive(dict, always_update=True)

        def render(self) -> Panel:
            """Render memory stats as a panel."""
            table = Table(show_header=False, show_edge=False, expand=True)
            table.add_column("key", style="dim")
            table.add_column("value")

            s = self.stats
            table.add_row("Decisions", str(s.get("decisions", 0)))
            table.add_row("Conventions", str(s.get("conventions", 0)))
            table.add_row("Failures", str(s.get("failures", 0)))
            table.add_row("Index files", str(s.get("index_files", 0)))

            tools = s.get("cli_tools", [])
            tool_str = ", ".join(f"[green]{t}[/green]" for t in tools) if tools else "[dim]none[/dim]"
            table.add_row("CLI Tools", tool_str)

            return Panel(table, title="[bold]Project[/bold]", border_style="dim")

    class OutputWidget(RichLog):
        """Scrollable output log for operation details."""

        pass

    class StatusWidget(Static):
        """Bottom status bar widget."""

        epic: reactive[str] = reactive("")
        phase: reactive[str] = reactive("")
        status_text: reactive[str] = reactive("Ready")

        def render(self) -> Text:
            """Render the status line."""
            parts: list[str] = []
            if self.epic:
                parts.append(f"[cyan]{self.epic}[/cyan]")
            if self.phase:
                parts.append(f"phase {self.phase}")
            parts.append(f"[dim]{self.status_text}[/dim]")
            return Text.from_markup(" │ ".join(parts))

    # -----------------------------------------------------------------------
    # Main Dashboard App
    # -----------------------------------------------------------------------

    class MusoniusDashboard(App):
        """Textual TUI dashboard for musonius orchestration.

        Split-pane view: pipeline progress on top, operation output center,
        memory sidebar, status footer.
        """

        CSS = """
        Screen {
            layout: grid;
            grid-size: 4 3;
            grid-columns: 3fr 1fr;
            grid-rows: auto 1fr auto;
        }

        #pipeline {
            column-span: 2;
            height: auto;
            max-height: 12;
        }

        #output {
            column-span: 1;
            height: 100%;
            border: solid dim;
        }

        #sidebar {
            column-span: 1;
            height: 100%;
        }

        #status {
            column-span: 2;
            height: 3;
            background: $surface;
            padding: 0 2;
        }
        """

        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("r", "refresh", "Refresh"),
        ]

        def __init__(
            self,
            project_root: Path,
            task: str = "",
            **kwargs: Any,
        ) -> None:
            super().__init__(**kwargs)
            self.project_root = project_root
            self.task = task
            self._pipeline_steps: list[dict[str, Any]] = []

        def compose(self) -> ComposeResult:
            """Build the dashboard layout."""
            yield Header(show_clock=True)
            yield PipelineWidget(id="pipeline")
            yield OutputWidget(id="output", highlight=True, markup=True)
            yield MemoryWidget(id="sidebar")
            yield StatusWidget(id="status")
            yield Footer()

        def on_mount(self) -> None:
            """Initialize dashboard state on mount."""
            self.title = f"Musonius — {self.project_root.name}"
            self.sub_title = self.task or "Dashboard"

            # Initialize pipeline steps
            self._pipeline_steps = [
                {"name": "Initialize", "status": StepStatus.PENDING, "detail": ""},
                {"name": "Plan", "status": StepStatus.PENDING, "detail": ""},
                {"name": "Prep", "status": StepStatus.PENDING, "detail": ""},
                {"name": "Verify", "status": StepStatus.PENDING, "detail": ""},
            ]
            self._update_pipeline()
            self._update_memory()

        def _update_pipeline(self) -> None:
            """Push current pipeline state to widget."""
            widget = self.query_one("#pipeline", PipelineWidget)
            widget.steps = list(self._pipeline_steps)

        def _update_memory(self) -> None:
            """Gather and push memory stats to widget."""
            stats: dict[str, Any] = {
                "decisions": 0,
                "conventions": 0,
                "failures": 0,
                "index_files": 0,
                "cli_tools": [],
            }

            musonius_dir = self.project_root / ".musonius"

            # Index
            index_dir = musonius_dir / "index"
            if index_dir.exists():
                stats["index_files"] = len(list(index_dir.glob("*")))

            # Memory
            db_path = musonius_dir / "memory" / "decisions.db"
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

            # CLI tools
            try:
                from musonius.orchestration.cli_backend import detect_cli_tools

                tools = detect_cli_tools()
                stats["cli_tools"] = list(tools.keys())
            except Exception:
                pass

            widget = self.query_one("#sidebar", MemoryWidget)
            widget.stats = stats

        def log_output(self, message: str, style: str = "") -> None:
            """Write a line to the output log.

            Args:
                message: Text to log.
                style: Optional Rich markup style.
            """
            output = self.query_one("#output", OutputWidget)
            if style:
                output.write(Text.from_markup(f"[{style}]{message}[/{style}]"))
            else:
                output.write(message)

        def set_step_status(
            self,
            index: int,
            status: str,
            detail: str = "",
        ) -> None:
            """Update a pipeline step's status.

            Args:
                index: Step index (0-based).
                status: New status from StepStatus.
                detail: Optional detail text.
            """
            if 0 <= index < len(self._pipeline_steps):
                step = self._pipeline_steps[index]
                if status == StepStatus.RUNNING and not step.get("start_time"):
                    step["start_time"] = time.monotonic()
                elif status in (StepStatus.COMPLETED, StepStatus.FAILED) and step.get("start_time"):
                    step["elapsed"] = time.monotonic() - step["start_time"]
                step["status"] = status
                if detail:
                    step["detail"] = detail
                self._update_pipeline()

        def set_epic(self, epic_id: str) -> None:
            """Update the status bar epic display."""
            status = self.query_one("#status", StatusWidget)
            status.epic = epic_id

        def set_status(self, text: str) -> None:
            """Update the status bar text."""
            status = self.query_one("#status", StatusWidget)
            status.status_text = text

        def action_refresh(self) -> None:
            """Handle the refresh keybinding."""
            self._update_memory()
            self._update_pipeline()

        def action_quit(self) -> None:
            """Handle the quit keybinding."""
            self.exit()


# ---------------------------------------------------------------------------
# Fallback for when Textual is not installed
# ---------------------------------------------------------------------------


def run_dashboard(project_root: Path, task: str = "") -> None:
    """Launch the Textual dashboard if available, otherwise fall back to Rich.

    Args:
        project_root: Project root path.
        task: Task description.
    """
    if TEXTUAL_AVAILABLE:
        app = MusoniusDashboard(project_root=project_root, task=task)
        app.run()
    else:
        from musonius.cli.display import render_status_dashboard

        logger.warning("Textual not installed, falling back to static display.")
        from musonius.cli.utils import console

        console.print(
            "[yellow]Install textual for the full dashboard:[/yellow] "
            "pip install textual"
        )
        console.print()
        render_status_dashboard(project_root)


def check_textual_available() -> bool:
    """Check if Textual is available.

    Returns:
        True if textual is importable.
    """
    return TEXTUAL_AVAILABLE
