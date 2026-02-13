"""Tests for the musonius doctor command."""

from __future__ import annotations

from typer.testing import CliRunner

from musonius.cli.main import app

runner = CliRunner()


class TestDoctorCommand:
    """Tests for the doctor CLI command."""

    def test_doctor_registered(self) -> None:
        """doctor command should be registered in the Typer app."""
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "health" in result.output.lower() or "diagnostic" in result.output.lower()

    def test_doctor_runs(self) -> None:
        """doctor command should run without errors."""
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        # Should contain health check table
        assert "Python" in result.output
        assert "Dependencies" in result.output

    def test_doctor_shows_python_version(self) -> None:
        """doctor should report the Python version."""
        result = runner.invoke(app, ["doctor"])
        assert "3." in result.output  # Python 3.x

    def test_doctor_checks_api_keys(self) -> None:
        """doctor should check for API keys."""
        result = runner.invoke(app, ["doctor"])
        assert "API keys" in result.output

    def test_doctor_checks_project_state(self) -> None:
        """doctor should check project initialization."""
        result = runner.invoke(app, ["doctor"])
        assert "Project" in result.output
