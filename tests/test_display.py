"""Tests for the enhanced display module."""

from __future__ import annotations

import time
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from musonius.cli.display import (
    PipelineProgress,
    StatusBar,
    StreamingDisplay,
    render_plan_markdown,
    render_verification_markdown,
)


# ---------------------------------------------------------------------------
# StreamingDisplay
# ---------------------------------------------------------------------------


class TestStreamingDisplay:
    """Tests for the StreamingDisplay context manager."""

    def test_creates_and_enters(self) -> None:
        """Should create a Live display on enter."""
        with patch("musonius.cli.display.console") as mock_console:
            display = StreamingDisplay("Testing...")
            with display:
                assert display._live is not None
                assert display._start_time > 0

    def test_update_detail(self) -> None:
        """Should update the detail text."""
        display = StreamingDisplay("Testing...")
        display._detail = ""
        display.update("Loading files...")
        assert display._detail == "Loading files..."

    def test_update_title(self) -> None:
        """Should update the title text."""
        display = StreamingDisplay("Original")
        display.update_title("New Title")
        assert display._title == "New Title"

    def test_complete_sets_state(self) -> None:
        """Should mark operation as completed."""
        display = StreamingDisplay("Testing...")
        display.complete("Done!")
        assert display._completed is True
        assert display._final_message == "Done!"

    def test_complete_defaults_to_title(self) -> None:
        """Complete without message should use the title."""
        display = StreamingDisplay("My Operation")
        display.complete()
        assert display._final_message == "My Operation"

    def test_build_display_returns_panel(self) -> None:
        """Should build a Rich Panel."""
        display = StreamingDisplay("Testing...")
        display._start_time = time.monotonic()
        panel = display._build_display()
        # Panel is a Rich renderable
        assert panel is not None


# ---------------------------------------------------------------------------
# PipelineProgress
# ---------------------------------------------------------------------------


class TestPipelineProgress:
    """Tests for the PipelineProgress multi-step tracker."""

    def test_step_tracking(self) -> None:
        """Should track steps with status transitions."""
        with patch("musonius.cli.display.console"):
            pipeline = PipelineProgress()
            # Don't actually enter Live context for testing
            pipeline._live = MagicMock()
            pipeline._start_time = time.monotonic()

            with pipeline.step("Step 1") as step:
                step.detail("Working...")

            assert len(pipeline._steps) == 1
            assert pipeline._steps[0]["status"] == "completed"
            assert pipeline._steps[0]["detail"] == "Working..."
            assert pipeline._steps[0]["elapsed"] is not None

    def test_failed_step(self) -> None:
        """Should mark step as failed on exception."""
        with patch("musonius.cli.display.console"):
            pipeline = PipelineProgress()
            pipeline._live = MagicMock()
            pipeline._start_time = time.monotonic()

            with pytest.raises(ValueError):
                with pipeline.step("Failing Step") as step:
                    raise ValueError("Boom")

            assert pipeline._steps[0]["status"] == "failed"

    def test_multiple_steps(self) -> None:
        """Should track multiple steps in order."""
        with patch("musonius.cli.display.console"):
            pipeline = PipelineProgress()
            pipeline._live = MagicMock()
            pipeline._start_time = time.monotonic()

            with pipeline.step("Init") as step:
                step.detail("Done")
            with pipeline.step("Plan") as step:
                step.detail("Generated")
            with pipeline.step("Prep") as step:
                step.detail("Written")

            assert len(pipeline._steps) == 3
            assert all(s["status"] == "completed" for s in pipeline._steps)
            assert [s["name"] for s in pipeline._steps] == ["Init", "Plan", "Prep"]

    def test_build_display_returns_table(self) -> None:
        """Should build a Rich Table."""
        pipeline = PipelineProgress()
        pipeline._steps = [
            {"name": "Test", "status": "completed", "detail": "OK", "elapsed": 1.5},
        ]
        table = pipeline._build_display()
        assert table is not None


# ---------------------------------------------------------------------------
# Markdown Rendering
# ---------------------------------------------------------------------------


class TestRenderPlanMarkdown:
    """Tests for render_plan_markdown."""

    def test_renders_plan(self) -> None:
        """Should render a Plan as markdown in a panel."""
        # Create a mock plan
        plan = MagicMock()
        plan.epic_id = "epic-001"
        plan.task_description = "Add rate limiting"

        phase = MagicMock()
        phase.title = "Setup"
        file_change = MagicMock()
        file_change.path = "api/rate_limit.py"
        file_change.action = "create"
        file_change.description = "Rate limiter module"
        phase.files = [file_change]
        phase.acceptance_criteria = ["Tests pass", "Rate limits enforced"]
        plan.phases = [phase]

        # Patch the isinstance check
        with patch("musonius.cli.display.console") as mock_console:
            with patch("musonius.planning.schemas.Plan", type(plan)):
                # Will print via console — just verify no exception
                render_plan_markdown(plan)

    def test_handles_non_plan(self) -> None:
        """Should handle non-Plan objects gracefully."""
        with patch("musonius.cli.display.console") as mock_console:
            render_plan_markdown("not a plan")
            mock_console.print.assert_called()


# ---------------------------------------------------------------------------
# StatusBar
# ---------------------------------------------------------------------------


class TestStatusBar:
    """Tests for the StatusBar widget."""

    def test_build_returns_panel(self, tmp_path: Path) -> None:
        """Should build a panel with project stats."""
        musonius_dir = tmp_path / ".musonius"
        musonius_dir.mkdir()
        (musonius_dir / "index").mkdir()
        # Create a dummy file
        (musonius_dir / "index" / "graph.json").write_text("{}")

        with patch("musonius.cli.display.console"):
            bar = StatusBar(tmp_path)
            panel = bar.build()
            assert panel is not None

    def test_gather_stats_empty_project(self, tmp_path: Path) -> None:
        """Should return zero stats for empty project."""
        musonius_dir = tmp_path / ".musonius"
        musonius_dir.mkdir()

        bar = StatusBar(tmp_path)
        stats = bar._gather_stats()
        assert stats["project"] == tmp_path.name
        assert stats["epic"] is None
        assert stats["index_files"] == 0

    def test_gather_stats_with_index(self, tmp_path: Path) -> None:
        """Should count index files."""
        musonius_dir = tmp_path / ".musonius"
        index_dir = musonius_dir / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "a.json").write_text("{}")
        (index_dir / "b.json").write_text("{}")

        bar = StatusBar(tmp_path)
        stats = bar._gather_stats()
        assert stats["index_files"] == 2

    def test_gather_stats_with_epic(self, tmp_path: Path) -> None:
        """Should detect latest epic."""
        musonius_dir = tmp_path / ".musonius"
        epic_dir = musonius_dir / "epics" / "epic-001"
        phases_dir = epic_dir / "phases"
        phases_dir.mkdir(parents=True)
        (phases_dir / "phase-01.md").write_text("# Phase 1")

        bar = StatusBar(tmp_path)
        stats = bar._gather_stats()
        assert stats["epic"] == "epic-001"
        assert "1" in stats["phase_progress"]

    def test_print_calls_console(self, tmp_path: Path) -> None:
        """Should print to console."""
        musonius_dir = tmp_path / ".musonius"
        musonius_dir.mkdir()

        with patch("musonius.cli.display.console") as mock_console:
            bar = StatusBar(tmp_path)
            bar.print()
            mock_console.print.assert_called()


# ---------------------------------------------------------------------------
# Dashboard availability
# ---------------------------------------------------------------------------


class TestDashboard:
    """Tests for dashboard module imports."""

    def test_check_textual_available(self) -> None:
        """Should report whether textual is importable."""
        from musonius.cli.dashboard import check_textual_available

        # Just verify it returns a bool
        result = check_textual_available()
        assert isinstance(result, bool)

    def test_run_dashboard_fallback(self, tmp_path: Path) -> None:
        """Should fall back to Rich display when Textual is unavailable."""
        with patch("musonius.cli.dashboard.TEXTUAL_AVAILABLE", False):
            with patch("musonius.cli.display.render_status_dashboard") as mock_render:
                with patch("musonius.cli.utils.console"):
                    from musonius.cli.dashboard import run_dashboard

                    run_dashboard(tmp_path, task="test")
                    mock_render.assert_called_once_with(tmp_path)
