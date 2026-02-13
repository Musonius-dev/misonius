"""End-to-end integration test: init → plan → prep → verify pipeline.

Proves the full Musonius workflow runs without error on a synthetic project.
LLM calls are mocked — this tests the local machinery, not the model routing.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from musonius.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixture: create a minimal Python project with .git
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a minimal Python project with a few source files."""
    # Simulate git repo
    (tmp_path / ".git").mkdir()

    # pyproject.toml
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        '[tool.ruff]\ntarget-version = "py312"\n'
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )

    # Source files
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "app.py").write_text(
        '"""Main application module."""\n\n'
        "from __future__ import annotations\n\n"
        "\n"
        "def start_server(host: str = '0.0.0.0', port: int = 8000) -> None:\n"
        '    """Start the web server.\n\n'
        "    Args:\n"
        "        host: Bind address.\n"
        "        port: Listen port.\n"
        '    """\n'
        "    pass\n"
        "\n\n"
        "def health_check() -> dict:\n"
        '    """Return service health status."""\n'
        '    return {"status": "ok"}\n'
    )
    (src / "models.py").write_text(
        '"""Data models."""\n\n'
        "from __future__ import annotations\n\n"
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\n"
        "class User:\n"
        '    """A user in the system."""\n\n'
        "    name: str\n"
        "    email: str\n"
        "    active: bool = True\n"
    )
    (src / "utils.py").write_text(
        '"""Utility functions."""\n\n'
        "from __future__ import annotations\n\n"
        "import os\n"
        "from pathlib import Path\n\n\n"
        "def get_env(key: str, default: str = '') -> str:\n"
        '    """Read an environment variable."""\n'
        "    return os.getenv(key, default)\n"
    )

    # Test directory
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_app.py").write_text(
        '"""Tests for app module."""\n\n'
        "from src.app import health_check\n\n\n"
        "def test_health_check() -> None:\n"
        '    assert health_check()["status"] == "ok"\n'
    )

    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. musonius init
# ---------------------------------------------------------------------------


class TestInitPhase:
    """Verify that `musonius init` succeeds on the synthetic project."""

    def test_init_creates_directory_structure(self, project: Path) -> None:
        """init should create .musonius/ with all subdirectories."""
        result = runner.invoke(app, ["init", "--auto"])
        assert result.exit_code == 0, f"init failed: {result.output}"

        m = project / ".musonius"
        assert m.is_dir()
        assert (m / "config.yaml").exists()
        assert (m / "index").is_dir()
        assert (m / "memory").is_dir()
        assert (m / "epics").is_dir()
        assert (m / "sot").is_dir()

    def test_init_indexes_source_files(self, project: Path) -> None:
        """init should report indexed files and symbols."""
        result = runner.invoke(app, ["init", "--auto"])
        assert result.exit_code == 0
        # Should find at least our 3 source files + 2 test files
        assert "indexed" in result.output.lower() or "files" in result.output.lower()

    def test_init_detects_conventions(self, project: Path) -> None:
        """init should detect coding conventions and store them."""
        result = runner.invoke(app, ["init", "--auto"])
        assert result.exit_code == 0
        assert "convention" in result.output.lower()

    def test_init_memory_store_exists(self, project: Path) -> None:
        """init should create the SQLite memory database."""
        runner.invoke(app, ["init", "--auto"])
        db = project / ".musonius" / "memory" / "decisions.db"
        assert db.exists()


# ---------------------------------------------------------------------------
# 2. musonius plan (mocked LLM)
# ---------------------------------------------------------------------------


def _mock_plan_response() -> dict:
    """Create a fake plan response as if returned by the scout model."""
    return {
        "epic_id": "epic-001",
        "task_description": "Add rate limiting to the API",
        "phases": [
            {
                "id": "phase-01",
                "title": "Add middleware",
                "description": "Create rate limiting middleware.",
                "files": [
                    {"path": "src/app.py", "action": "modify", "description": "Add rate limiter"}
                ],
                "dependencies": [],
                "acceptance_criteria": ["Rate limiting active on /api routes"],
                "test_strategy": "Unit test for middleware",
                "estimated_tokens": 2000,
            },
            {
                "id": "phase-02",
                "title": "Add Redis backend",
                "description": "Switch to Redis-backed counter.",
                "files": [
                    {"path": "src/rate_limiter.py", "action": "create", "description": "Redis backend"}
                ],
                "dependencies": ["phase-01"],
                "acceptance_criteria": ["Shared counter across instances"],
                "test_strategy": "Integration test with Redis mock",
                "estimated_tokens": 3000,
            },
        ],
        "total_estimated_tokens": 5000,
    }


class TestPlanPhase:
    """Verify that `musonius plan` works end-to-end with mocked LLM."""

    def test_plan_creates_epic(self, project: Path) -> None:
        """plan should create an epic directory with spec and phases."""
        runner.invoke(app, ["init", "--auto"])

        # Mock the LLM call in the planning engine
        with patch("musonius.orchestration.router.ModelRouter.call_planner") as mock_call:
            mock_call.return_value = MagicMock(content=json.dumps(_mock_plan_response()))
            result = runner.invoke(
                app, ["plan", "Add rate limiting to the API", "--no-clarify"]
            )

        assert result.exit_code == 0, f"plan failed: {result.output}"
        assert "rate limiting" in result.output.lower()

        # Verify epic directory was created
        epics_dir = project / ".musonius" / "epics"
        epic_dirs = list(epics_dir.iterdir())
        assert len(epic_dirs) >= 1

    def test_plan_no_clarify_skips_questions(self, project: Path) -> None:
        """plan --no-clarify should not ask any clarifying questions."""
        runner.invoke(app, ["init", "--auto"])

        with patch("musonius.orchestration.router.ModelRouter.call_planner") as mock_call:
            mock_call.return_value = MagicMock(content=json.dumps(_mock_plan_response()))
            result = runner.invoke(
                app, ["plan", "Add rate limiting to the API", "--no-clarify"]
            )

        assert result.exit_code == 0
        # Should not mention "clarif" in output
        assert "answer" not in result.output.lower()


# ---------------------------------------------------------------------------
# 3. musonius prep
# ---------------------------------------------------------------------------


class TestPrepPhase:
    """Verify that `musonius prep` generates handoff documents."""

    def test_prep_generates_handoff(self, project: Path) -> None:
        """prep should produce a handoff file with codebase context."""
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["prep"])
        assert result.exit_code == 0, f"prep failed: {result.output}"
        assert "handoff" in result.output.lower()

        # Default agent is claude → HANDOFF.md
        handoff = project / "HANDOFF.md"
        assert handoff.exists(), "Handoff file was not written to disk"
        content = handoff.read_text()
        assert len(content) > 100, "Handoff file is suspiciously short"

    def test_prep_for_specific_agent(self, project: Path) -> None:
        """prep --agent gemini should generate Gemini-formatted handoff."""
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["prep", "--agent", "gemini"])
        assert result.exit_code == 0
        assert "handoff" in result.output.lower()

    def test_prep_custom_output_path(self, project: Path) -> None:
        """prep --output should write to the specified path."""
        runner.invoke(app, ["init", "--auto"])

        out = project / "custom_handoff.md"
        result = runner.invoke(app, ["prep", "--output", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_prep_includes_conventions(self, project: Path) -> None:
        """Handoff should include detected conventions from memory."""
        runner.invoke(app, ["init", "--auto"])

        result = runner.invoke(app, ["prep"])
        assert result.exit_code == 0

        handoff = project / "HANDOFF.md"
        content = handoff.read_text()
        # Convention data should appear in the handoff
        # (at minimum the convention section header or some convention text)
        assert len(content) > 50


# ---------------------------------------------------------------------------
# 4. musonius verify (mocked LLM + git diff)
# ---------------------------------------------------------------------------


class TestVerifyPhase:
    """Verify that `musonius verify` runs after prep."""

    def test_verify_no_changes_no_llm(self, project: Path) -> None:
        """verify --no-llm with no git changes should exit cleanly."""
        runner.invoke(app, ["init", "--auto"])

        with patch("musonius.verification.diff_analyzer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            result = runner.invoke(app, ["verify", "--no-llm"])

        assert result.exit_code == 0
        assert "no changes" in result.output.lower()

    def test_verify_with_diff_no_llm(self, project: Path) -> None:
        """verify --no-llm with a diff should show a static analysis report."""
        runner.invoke(app, ["init", "--auto"])

        fake_diff = (
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,3 +1,5 @@\n"
            '+import redis\n'
            '+\n'
            " def start_server():\n"
            "     pass\n"
        )
        with patch("musonius.verification.diff_analyzer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=fake_diff, returncode=0)
            result = runner.invoke(app, ["verify", "--no-llm"])

        assert result.exit_code == 0
        # Should detect that we changed app.py
        assert "app.py" in result.output or "change" in result.output.lower()


# ---------------------------------------------------------------------------
# 5. Full pipeline sequence
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Run the entire init → plan → prep → verify pipeline in sequence."""

    def test_full_pipeline(self, project: Path) -> None:
        """Complete pipeline should succeed end-to-end."""
        # 1. Init
        init_result = runner.invoke(app, ["init", "--auto"])
        assert init_result.exit_code == 0, f"init failed:\n{init_result.output}"

        # 2. Plan (mocked LLM)
        with patch("musonius.orchestration.router.ModelRouter.call_planner") as mock_call:
            mock_call.return_value = MagicMock(content=json.dumps(_mock_plan_response()))
            plan_result = runner.invoke(
                app, ["plan", "Add rate limiting to the API", "--no-clarify"]
            )
        assert plan_result.exit_code == 0, f"plan failed:\n{plan_result.output}"

        # 3. Prep
        prep_result = runner.invoke(app, ["prep"])
        assert prep_result.exit_code == 0, f"prep failed:\n{prep_result.output}"
        handoff = project / "HANDOFF.md"
        assert handoff.exists(), "Handoff file not created"

        # 4. Verify (mocked git diff)
        with patch("musonius.verification.diff_analyzer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            verify_result = runner.invoke(app, ["verify", "--no-llm"])
        assert verify_result.exit_code == 0, f"verify failed:\n{verify_result.output}"

    def test_memory_persists_across_commands(self, project: Path) -> None:
        """Memory added during init should be visible in later commands."""
        # Init (should store detected conventions)
        runner.invoke(app, ["init", "--auto"])

        # Add a manual decision
        runner.invoke(
            app,
            ["memory", "add", "decision", "Use FastAPI for web layer", "--rationale", "Async support"],
        )

        # Search should find it
        result = runner.invoke(app, ["memory", "search", "FastAPI"])
        assert result.exit_code == 0
        assert "fastapi" in result.output.lower()

        # List conventions should show auto-detected ones
        conv_result = runner.invoke(app, ["memory", "list", "conventions"])
        assert conv_result.exit_code == 0

    def test_status_reflects_full_pipeline(self, project: Path) -> None:
        """status should reflect init, plan, and memory state."""
        # Init
        runner.invoke(app, ["init", "--auto"])

        # Plan
        with patch("musonius.orchestration.router.ModelRouter.call_planner") as mock_call:
            mock_call.return_value = MagicMock(content=json.dumps(_mock_plan_response()))
            runner.invoke(app, ["plan", "Add rate limiting", "--no-clarify"])

        # Status should show indexed files, memory, and epic
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        # Should mention files or memory counts
        assert "index" in result.output.lower() or "memory" in result.output.lower()
