"""Tests for the CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from musonius.cli.main import app

runner = CliRunner()


class TestMainApp:
    """Tests for the top-level Typer app and global options."""

    def test_help(self) -> None:
        """--help should display help text with all commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "spec-driven" in result.output.lower() or "musonius" in result.output.lower()
        # All registered commands should appear
        for cmd in ("init", "plan", "prep", "verify", "review", "status", "memory", "agents"):
            assert cmd in result.output

    def test_version(self) -> None:
        """--version should display version."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_no_args_shows_help(self) -> None:
        """Running with no arguments should display usage info."""
        result = runner.invoke(app, [])
        # Typer uses exit code 0 or 2 for no_args_is_help depending on version
        assert "Usage" in result.output or "Commands" in result.output

    def test_debug_flag(self) -> None:
        """--debug should enable debug logging without crashing."""
        result = runner.invoke(app, ["--debug", "--help"])
        assert result.exit_code == 0


class TestInitCommand:
    """Tests for `musonius init`."""

    def test_init_help(self) -> None:
        """init --help should display help."""
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "initialize" in result.output.lower()

    def test_init_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """musonius init should create .musonius/ directory structure."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()

        result = runner.invoke(app, ["init", "--auto"])
        assert result.exit_code == 0

        musonius_dir = tmp_path / ".musonius"
        assert musonius_dir.is_dir()
        assert (musonius_dir / "config.yaml").exists()
        assert (musonius_dir / "index").is_dir()
        assert (musonius_dir / "memory").is_dir()
        assert (musonius_dir / "epics").is_dir()
        assert (musonius_dir / "sot").is_dir()

    def test_init_with_language(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """init --language should set the language in config."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()

        result = runner.invoke(app, ["init", "--auto", "--language", "typescript"])
        assert result.exit_code == 0

        import yaml

        config_path = tmp_path / ".musonius" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        assert config["project"]["language"] == "typescript"

    def test_init_reinit_auto(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Re-running init --auto on an existing project should succeed."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()

        # First init
        runner.invoke(app, ["init", "--auto"])
        # Second init
        result = runner.invoke(app, ["init", "--auto"])
        assert result.exit_code == 0

    def test_init_reinit_interactive_decline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-running init without --auto should prompt, declining exits."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()

        # First init
        runner.invoke(app, ["init", "--auto"])
        # Second init — user declines
        result = runner.invoke(app, ["init"], input="n\n")
        assert result.exit_code == 0

    def test_init_output_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """init should print helpful next-step guidance."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()

        result = runner.invoke(app, ["init", "--auto"])
        assert result.exit_code == 0
        assert "initialized" in result.output.lower()
        assert "musonius plan" in result.output


class TestPlanCommand:
    """Tests for `musonius plan`."""

    def test_plan_help(self) -> None:
        """plan --help should display help."""
        result = runner.invoke(app, ["plan", "--help"])
        assert result.exit_code == 0
        assert "task" in result.output.lower()

    def test_plan_requires_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """plan should fail if project is not initialized."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["plan", "add feature"])
        assert result.exit_code == 1

    def test_plan_requires_task_argument(self) -> None:
        """plan without a task argument should fail."""
        result = runner.invoke(app, ["plan"])
        assert result.exit_code != 0

    def test_plan_shows_task_panel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """plan should display the task in the output."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["plan", "add rate limiting", "--no-clarify"])
        # The plan generation will fail (no LLM key) but should show the task
        assert "rate limiting" in result.output


class TestPrepCommand:
    """Tests for `musonius prep`."""

    def test_prep_help(self) -> None:
        """prep --help should display help."""
        result = runner.invoke(app, ["prep", "--help"])
        assert result.exit_code == 0
        assert "agent" in result.output.lower()

    def test_prep_requires_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """prep should fail if project is not initialized."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["prep"])
        assert result.exit_code == 1

    def test_prep_generates_handoff(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """prep should generate a handoff file for the default agent."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["prep"])
        assert result.exit_code == 0
        assert "handoff" in result.output.lower()

    def test_prep_unknown_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """prep with an unknown agent should show a helpful error."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["prep", "--agent", "nonexistent"])
        assert result.exit_code == 1
        assert "unknown" in result.output.lower() or "available" in result.output.lower()

    def test_prep_custom_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """prep --output should write to the specified path."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        out_file = tmp_path / "my_handoff.md"
        result = runner.invoke(app, ["prep", "--output", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()


class TestVerifyCommand:
    """Tests for `musonius verify`."""

    def test_verify_help(self) -> None:
        """verify --help should display help."""
        result = runner.invoke(app, ["verify", "--help"])
        assert result.exit_code == 0
        assert "verify" in result.output.lower()

    def test_verify_requires_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """verify should fail if project is not initialized."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["verify"])
        assert result.exit_code == 1

    def test_verify_no_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """verify with no git changes should report no changes."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        # Mock subprocess in diff_analyzer (verify.py no longer imports subprocess directly)
        with patch("musonius.verification.diff_analyzer.subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            mock_run.return_value.returncode = 0
            result = runner.invoke(app, ["verify", "--no-llm"])

        assert "no changes" in result.output.lower()

    def test_verify_severity_filter_option(self) -> None:
        """verify --help should show the --severity option."""
        result = runner.invoke(app, ["verify", "--help"])
        assert "--severity" in result.output

    def test_verify_fix_option(self) -> None:
        """verify --help should show the --fix option."""
        result = runner.invoke(app, ["verify", "--help"])
        assert "--fix" in result.output

    def test_verify_no_llm_option(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """verify --no-llm should skip LLM verification."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        with patch("musonius.verification.diff_analyzer.subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            mock_run.return_value.returncode = 0
            result = runner.invoke(app, ["verify", "--no-llm"])

        assert result.exit_code == 0


class TestReviewCommand:
    """Tests for `musonius review`."""

    def test_review_help(self) -> None:
        """review --help should display help."""
        result = runner.invoke(app, ["review", "--help"])
        assert result.exit_code == 0
        assert "review" in result.output.lower()

    def test_review_requires_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """review should fail if project is not initialized."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["review"])
        assert result.exit_code == 1


class TestRollbackCommand:
    """Tests for `musonius rollback`."""

    def test_rollback_help(self) -> None:
        """rollback --help should display help."""
        result = runner.invoke(app, ["rollback", "--help"])
        assert result.exit_code == 0
        assert "rollback" in result.output.lower() or "restore" in result.output.lower()

    def test_rollback_requires_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """rollback should fail if project is not initialized."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["rollback", "epic-001", "phase-1"])
        assert result.exit_code == 1


class TestStatusCommand:
    """Tests for `musonius status`."""

    def test_status_requires_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """status should fail without initialization."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1

    def test_status_after_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """status should work after initialization."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "index" in result.output.lower() or "memory" in result.output.lower()


class TestMemorySubcommands:
    """Tests for `musonius memory` subcommands."""

    def test_memory_help(self) -> None:
        """memory --help should display help with subcommands."""
        result = runner.invoke(app, ["memory", "--help"])
        assert result.exit_code == 0
        assert "search" in result.output
        assert "list" in result.output
        assert "add" in result.output
        assert "show" in result.output
        assert "forget" in result.output

    def test_memory_search_requires_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory search should fail without initialization."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["memory", "search", "auth"])
        assert result.exit_code == 1

    def test_memory_add_decision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory add decision should record a decision."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(
            app, ["memory", "add", "decision", "Use SQLite for storage", "--rationale", "Lightweight"]
        )
        assert result.exit_code == 0
        assert "added" in result.output.lower()

    def test_memory_add_convention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory add convention should record a convention."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(
            app, ["memory", "add", "convention", "All functions need docstrings", "--category", "naming"]
        )
        assert result.exit_code == 0
        assert "added" in result.output.lower()

    def test_memory_add_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory add failure should record a failure."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(
            app,
            ["memory", "add", "failure", "Used raw SQL", "--rationale", "Injection vulnerability"],
        )
        assert result.exit_code == 0
        assert "added" in result.output.lower()

    def test_memory_add_unknown_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory add with unknown type should fail."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["memory", "add", "bogus", "whatever"])
        assert result.exit_code == 1

    def test_memory_list_decisions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory list decisions should show decisions (empty or populated)."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        # List when empty
        result = runner.invoke(app, ["memory", "list", "decisions"])
        assert result.exit_code == 0

    def test_memory_list_unknown_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory list with unknown type should fail."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["memory", "list", "bananas"])
        assert result.exit_code == 1

    def test_memory_search_no_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory search with no matching entries should report no results."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["memory", "search", "nonexistent_topic"])
        assert result.exit_code == 0
        assert "no results" in result.output.lower()

    def test_memory_search_finds_added_decision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory search should find a previously added decision."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        runner.invoke(
            app, ["memory", "add", "decision", "Use FastAPI for web framework"]
        )
        result = runner.invoke(app, ["memory", "search", "FastAPI"])
        assert result.exit_code == 0
        assert "fastapi" in result.output.lower()

    def test_memory_show_decision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory show should display details of a specific decision."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        runner.invoke(
            app, ["memory", "add", "decision", "Use SQLite for storage", "--rationale", "Lightweight"]
        )
        result = runner.invoke(app, ["memory", "show", "decision", "1"])
        assert result.exit_code == 0
        assert "sqlite" in result.output.lower()

    def test_memory_show_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory show with non-existent ID should report not found."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["memory", "show", "decision", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_memory_show_unknown_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory show with unknown type should fail."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["memory", "show", "bogus", "1"])
        assert result.exit_code == 1
        assert "unknown" in result.output.lower()

    def test_memory_forget_decision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory forget --force should remove a decision."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        runner.invoke(app, ["memory", "add", "decision", "Temporary decision"])
        result = runner.invoke(app, ["memory", "forget", "decision", "1", "--force"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()

    def test_memory_forget_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory forget with non-existent ID should report not found."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["memory", "forget", "decision", "999", "--force"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_memory_forget_unknown_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory forget with unknown type should fail."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["memory", "forget", "bogus", "1", "--force"])
        assert result.exit_code == 1
        assert "unknown" in result.output.lower()

    def test_memory_forget_confirmation_decline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory forget without --force should prompt and allow decline."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        runner.invoke(app, ["memory", "add", "decision", "Keep this one"])
        result = runner.invoke(app, ["memory", "forget", "decision", "1"], input="n\n")
        assert result.exit_code == 0

    def test_memory_show_convention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory show convention should display convention details."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        runner.invoke(
            app, ["memory", "add", "convention", "Use type hints everywhere", "--category", "style"]
        )
        result = runner.invoke(app, ["memory", "show", "convention", "1"])
        assert result.exit_code == 0
        assert "type hints" in result.output.lower()

    def test_memory_show_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """memory show failure should display failure details."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        runner.invoke(
            app, ["memory", "add", "failure", "Used raw SQL strings", "--rationale", "SQL injection risk"]
        )
        result = runner.invoke(app, ["memory", "show", "failure", "1"])
        assert result.exit_code == 0
        assert "raw sql" in result.output.lower()


class TestAgentsSubcommands:
    """Tests for `musonius agents` subcommands."""

    def test_agents_help(self) -> None:
        """agents --help should display help."""
        result = runner.invoke(app, ["agents", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "info" in result.output

    def test_agents_list(self) -> None:
        """agents list should display all registered plugins."""
        result = runner.invoke(app, ["agents", "list"])
        assert result.exit_code == 0
        assert "claude" in result.output.lower()
        assert "gemini" in result.output.lower()

    def test_agents_info_claude(self) -> None:
        """agents info claude should display Claude plugin details."""
        result = runner.invoke(app, ["agents", "info", "claude"])
        assert result.exit_code == 0
        assert "claude" in result.output.lower()

    def test_agents_info_unknown(self) -> None:
        """agents info with unknown slug should show error."""
        result = runner.invoke(app, ["agents", "info", "nonexistent"])
        assert result.exit_code == 1
        assert "unknown" in result.output.lower() or "available" in result.output.lower()

    def test_agents_add_help(self) -> None:
        """agents add --help should display help."""
        result = runner.invoke(app, ["agents", "add", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output.lower()

    def test_agents_add_creates_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """agents add should create a YAML agent definition file."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(
            app,
            [
                "agents", "add",
                "--name", "TestBot",
                "--slug", "testbot",
                "--description", "A test agent",
                "--format", "generic",
                "--max-tokens", "64000",
            ],
        )
        assert result.exit_code == 0
        assert "created" in result.output.lower()

        # Verify the YAML file was created
        yaml_path = tmp_path / ".musonius" / "agents" / "testbot.yaml"
        assert yaml_path.exists()


class TestPlanOptions:
    """Tests for `musonius plan` additional options."""

    def test_plan_from_issue_help(self) -> None:
        """plan --help should show the --from-issue option."""
        result = runner.invoke(app, ["plan", "--help"])
        assert "--from-issue" in result.output

    def test_plan_clarify_no_clarify(self) -> None:
        """plan --help should show the --clarify/--no-clarify option."""
        result = runner.invoke(app, ["plan", "--help"])
        assert "clarify" in result.output.lower()


class TestPrepOptions:
    """Tests for `musonius prep` additional options."""

    def test_prep_phase_help(self) -> None:
        """prep --help should show the --phase option."""
        result = runner.invoke(app, ["prep", "--help"])
        assert "--phase" in result.output

    def test_prep_run_help(self) -> None:
        """prep --help should show the --run option."""
        result = runner.invoke(app, ["prep", "--help"])
        assert "--run" in result.output

    def test_prep_budget_help(self) -> None:
        """prep --help should show the --budget option."""
        result = runner.invoke(app, ["prep", "--help"])
        assert "--budget" in result.output

    def test_prep_level_help(self) -> None:
        """prep --help should show the --level option."""
        result = runner.invoke(app, ["prep", "--help"])
        assert "--level" in result.output


class TestStatusEpicProgress:
    """Tests for status command epic progress display."""

    def test_status_shows_epic_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """status should show epic progress when epics exist."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        runner.invoke(app, ["init", "--auto"])

        # Create an epic with phases
        epic_dir = tmp_path / ".musonius" / "epics" / "epic-001"
        epic_dir.mkdir(parents=True)
        (epic_dir / "spec.md").write_text("# Add rate limiting\nDescription here.")
        phases_dir = epic_dir / "phases"
        phases_dir.mkdir()
        (phases_dir / "phase-01.md").write_text("# Phase 1\nSetup middleware.")
        (phases_dir / "phase-02.md").write_text("# Phase 2\nAdd Redis backend.")

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "epic-001" in result.output
        assert "2" in result.output  # 2 phases


class TestErrorHandling:
    """Tests for the error handling decorator and utilities."""

    def test_handle_errors_keyboard_interrupt(self) -> None:
        """KeyboardInterrupt should be caught and result in exit code 130."""
        from musonius.cli.utils import handle_errors

        @handle_errors
        def raises_keyboard_interrupt() -> None:
            raise KeyboardInterrupt

        import typer

        with pytest.raises(typer.Exit) as exc_info:
            raises_keyboard_interrupt()
        assert exc_info.value.exit_code == 130

    def test_handle_errors_generic_exception(self) -> None:
        """Unexpected exceptions should be caught and result in exit code 1."""
        from musonius.cli.utils import handle_errors

        @handle_errors
        def raises_value_error() -> None:
            raise ValueError("test error")

        import typer

        with pytest.raises(typer.Exit) as exc_info:
            raises_value_error()
        assert exc_info.value.exit_code == 1

    def test_handle_errors_typer_exit_passthrough(self) -> None:
        """typer.Exit should pass through without being caught."""
        import typer

        from musonius.cli.utils import handle_errors

        @handle_errors
        def raises_typer_exit() -> None:
            raise typer.Exit(42)

        with pytest.raises(typer.Exit) as exc_info:
            raises_typer_exit()
        assert exc_info.value.exit_code == 42


class TestProjectDetection:
    """Tests for project root detection utilities."""

    def test_find_project_root_with_musonius_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """find_project_root should detect .musonius/ directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".musonius").mkdir()

        from musonius.cli.utils import find_project_root

        assert find_project_root() == tmp_path

    def test_find_project_root_with_git_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """find_project_root should detect .git/ directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()

        from musonius.cli.utils import find_project_root

        assert find_project_root() == tmp_path

    def test_find_project_root_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """find_project_root should fall back to cwd when no markers found."""
        monkeypatch.chdir(tmp_path)

        from musonius.cli.utils import find_project_root

        result = find_project_root()
        assert result == tmp_path

    def test_require_initialized_fails_without_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """require_initialized should raise typer.Exit(1) when not initialized."""
        monkeypatch.chdir(tmp_path)

        import typer

        from musonius.cli.utils import require_initialized

        with pytest.raises(typer.Exit) as exc_info:
            require_initialized()
        assert exc_info.value.exit_code == 1
