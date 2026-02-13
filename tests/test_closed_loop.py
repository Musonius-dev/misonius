"""Tests for the closed-loop planning system.

Validates decision extraction, SOT file generation, plan validation wiring,
verification outcome recording, and the `musonius go` command.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from musonius.cli.main import app
from musonius.memory.store import MemoryStore
from musonius.planning.engine import PlanningEngine
from musonius.planning.schemas import FileChange, Phase, Plan
from musonius.verification.engine import VerificationEngine, VerificationResult
from musonius.verification.severity import Finding, Severity

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    """Create a temporary memory store."""
    db_path = tmp_path / "test.db"
    s = MemoryStore(db_path)
    s.initialize()
    return s


@pytest.fixture
def engine(tmp_path: Path, store: MemoryStore) -> PlanningEngine:
    """Create a PlanningEngine with mocked router."""
    router = MagicMock()
    return PlanningEngine(memory=store, router=router, project_root=tmp_path)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a minimal Python project with .git for CLI tests."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "app.py").write_text(
        "def start_server() -> None:\n    pass\n"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Decision Extraction
# ---------------------------------------------------------------------------


class TestDecisionExtraction:
    """Tests for extracting architectural decisions from plan output."""

    def test_extracts_decisions_from_raw_data(self, engine: PlanningEngine, store: MemoryStore) -> None:
        """Should store decisions from architecture_decisions in plan JSON."""
        raw_data = {
            "phases": [],
            "architecture_decisions": [
                {
                    "summary": "Use FastAPI for web layer",
                    "rationale": "Async support and auto-docs",
                    "category": "architecture",
                    "files_affected": ["src/app.py"],
                },
                {
                    "summary": "Redis for rate limiting",
                    "rationale": "Shared state across instances",
                    "category": "dependency",
                    "files_affected": ["src/rate_limiter.py"],
                },
            ],
        }

        count = engine._extract_and_store_decisions(raw_data, "epic-001")
        assert count == 2

        decisions = store.get_all_decisions()
        assert len(decisions) == 2
        summaries = [d["summary"] for d in decisions]
        assert "Use FastAPI for web layer" in summaries
        assert "Redis for rate limiting" in summaries

    def test_skips_empty_decisions(self, engine: PlanningEngine, store: MemoryStore) -> None:
        """Should skip decisions with no summary."""
        raw_data = {
            "phases": [],
            "architecture_decisions": [
                {"summary": "", "rationale": "empty"},
                {"rationale": "no summary field"},
            ],
        }

        count = engine._extract_and_store_decisions(raw_data, "epic-002")
        assert count == 0
        assert len(store.get_all_decisions()) == 0

    def test_no_decisions_key(self, engine: PlanningEngine, store: MemoryStore) -> None:
        """Should handle missing architecture_decisions gracefully."""
        raw_data = {"phases": []}

        count = engine._extract_and_store_decisions(raw_data, "epic-003")
        assert count == 0

    def test_decision_stores_epic_id(self, engine: PlanningEngine, store: MemoryStore) -> None:
        """Should associate decisions with the correct epic ID."""
        raw_data = {
            "phases": [],
            "architecture_decisions": [
                {
                    "summary": "Test decision",
                    "rationale": "Testing",
                    "category": "pattern",
                },
            ],
        }

        engine._extract_and_store_decisions(raw_data, "epic-test-42")
        decisions = store.get_all_decisions()
        assert decisions[0]["epic_id"] == "epic-test-42"
        assert decisions[0]["category"] == "pattern"


# ---------------------------------------------------------------------------
# 2. SOT File Generation
# ---------------------------------------------------------------------------


class TestSOTGeneration:
    """Tests for Source of Truth file generation."""

    def test_generates_sot_files(self, engine: PlanningEngine) -> None:
        """Should create versioned SOT files from decisions."""
        raw_data = {
            "phases": [],
            "architecture_decisions": [
                {
                    "summary": "Use PostgreSQL for persistence",
                    "rationale": "ACID compliance and JSON support",
                    "category": "architecture",
                    "files_affected": ["src/db.py"],
                },
            ],
        }

        files = engine._generate_sot_files(raw_data, "epic-sot-01")
        assert len(files) == 1

        sot_file = files[0]
        assert sot_file.name == "ARCH-001.md"
        content = sot_file.read_text()
        assert "Use PostgreSQL for persistence" in content
        assert "ACID compliance" in content
        assert "epic-sot-01" in content

    def test_increments_sot_ids(self, engine: PlanningEngine) -> None:
        """Should auto-increment SOT IDs within the same prefix."""
        raw_data = {
            "phases": [],
            "architecture_decisions": [
                {
                    "summary": "First arch decision",
                    "rationale": "Reason 1",
                    "category": "architecture",
                },
                {
                    "summary": "Second arch decision",
                    "rationale": "Reason 2",
                    "category": "architecture",
                },
            ],
        }

        files = engine._generate_sot_files(raw_data, "epic-inc")
        assert len(files) == 2
        assert files[0].name == "ARCH-001.md"
        assert files[1].name == "ARCH-002.md"

    def test_different_category_prefixes(self, engine: PlanningEngine) -> None:
        """Should use correct prefix for each category."""
        raw_data = {
            "phases": [],
            "architecture_decisions": [
                {"summary": "API contract", "rationale": "r1", "category": "api"},
                {"summary": "Auth pattern", "rationale": "r2", "category": "security"},
                {"summary": "Caching", "rationale": "r3", "category": "performance"},
                {"summary": "Library choice", "rationale": "r4", "category": "dependency"},
            ],
        }

        files = engine._generate_sot_files(raw_data, "epic-cat")
        names = [f.name for f in files]
        assert "API-001.md" in names
        assert "SEC-001.md" in names
        assert "PERF-001.md" in names
        assert "DEP-001.md" in names

    def test_no_decisions_no_files(self, engine: PlanningEngine) -> None:
        """Should create no files when there are no decisions."""
        files = engine._generate_sot_files({"phases": []}, "epic-empty")
        assert len(files) == 0

    def test_sot_directory_created(self, engine: PlanningEngine) -> None:
        """Should create the sot directory if it doesn't exist."""
        sot_dir = engine.project_root / ".musonius" / "sot"
        assert not sot_dir.exists()

        raw_data = {
            "phases": [],
            "architecture_decisions": [
                {"summary": "Test", "rationale": "r", "category": "general"},
            ],
        }

        engine._generate_sot_files(raw_data, "epic-dir")
        assert sot_dir.exists()


# ---------------------------------------------------------------------------
# 3. Plan Validation Wiring
# ---------------------------------------------------------------------------


class TestPlanValidationWiring:
    """Tests that validate_plan is called during plan generation."""

    def test_generate_plan_calls_validation(self, engine: PlanningEngine) -> None:
        """generate_plan should call validate_plan and log warnings."""
        plan_json = json.dumps({
            "phases": [
                {
                    "id": "phase-1",
                    "title": "Add feature",
                    "description": "Add a feature",
                    "files": [
                        {"path": "src/app.py", "action": "modify", "description": "Add endpoint"}
                    ],
                    "acceptance_criteria": [],  # Missing — should trigger warning
                    "test_strategy": "",  # Missing — should trigger warning
                }
            ],
            "architecture_decisions": [],
        })

        engine.router.call_planner.return_value = MagicMock(content=plan_json)

        with patch("musonius.planning.engine.logger") as mock_logger:
            plan = engine.generate_plan("Add feature")

        # Should have logged validation warnings
        warning_calls = [c for c in mock_logger.warning.call_args_list if "validation" in str(c).lower()]
        assert len(warning_calls) >= 1  # At least the acceptance_criteria warning


# ---------------------------------------------------------------------------
# 4. Verification Outcome Recording
# ---------------------------------------------------------------------------


class TestVerificationOutcomeRecording:
    """Tests for recording verification outcomes in memory."""

    def test_records_passed_outcome(self, store: MemoryStore, tmp_path: Path) -> None:
        """Should record PASSED verification as a decision."""
        engine = VerificationEngine(memory=store, repo_path=tmp_path)
        result = VerificationResult(
            epic_id="epic-pass",
            phase_id="1",
            findings=[],
            passed=True,
            files_changed=["src/app.py"],
        )

        engine._record_verification_outcome(result)

        decisions = store.search_decisions("Verification")
        assert len(decisions) == 1
        assert "PASSED" in decisions[0]["summary"]
        assert "epic-pass" in decisions[0]["summary"]

    def test_records_failed_outcome(self, store: MemoryStore, tmp_path: Path) -> None:
        """Should record FAILED verification with finding counts."""
        engine = VerificationEngine(memory=store, repo_path=tmp_path)
        result = VerificationResult(
            epic_id="epic-fail",
            phase_id="2",
            findings=[
                Finding(category="security", severity=Severity.CRITICAL, message="Hardcoded secret"),
                Finding(category="missing", severity=Severity.MAJOR, message="Missing tests"),
            ],
            passed=False,
            files_changed=["src/auth.py", "src/config.py"],
        )

        engine._record_verification_outcome(result)

        decisions = store.search_decisions("Verification")
        assert len(decisions) == 1
        assert "FAILED" in decisions[0]["summary"]
        assert "1 critical" in decisions[0]["rationale"]
        assert "1 major" in decisions[0]["rationale"]

    def test_learns_from_major_failures(self, store: MemoryStore, tmp_path: Path) -> None:
        """Should record both CRITICAL and MAJOR findings as failures."""
        engine = VerificationEngine(memory=store, repo_path=tmp_path)
        result = VerificationResult(
            epic_id="epic-learn",
            findings=[
                Finding(
                    category="security",
                    severity=Severity.CRITICAL,
                    message="SQL injection",
                    file_path="src/db.py",
                    suggestion="Use parameterized queries",
                ),
                Finding(
                    category="missing",
                    severity=Severity.MAJOR,
                    message="No input validation",
                    file_path="src/api.py",
                    suggestion="Add pydantic validation",
                ),
                Finding(
                    category="style",
                    severity=Severity.MINOR,
                    message="Missing docstring",
                    file_path="src/utils.py",
                ),
            ],
        )

        engine._learn_from_failures(result)

        failures = store.get_all_failures()
        # Should record both critical and major, but not minor
        assert len(failures) == 2
        approaches = [f["approach"] for f in failures]
        assert any("SQL injection" in a for a in approaches)
        assert any("No input validation" in a for a in approaches)


# ---------------------------------------------------------------------------
# 5. Enhanced Prompt (architecture_decisions in schema)
# ---------------------------------------------------------------------------


class TestEnhancedPrompt:
    """Tests that the prompt now requests architecture_decisions."""

    def test_prompt_includes_architecture_decisions_schema(self) -> None:
        """System prompt should include the architecture_decisions JSON schema."""
        from musonius.planning.prompts import PLAN_SYSTEM_PROMPT

        assert "architecture_decisions" in PLAN_SYSTEM_PROMPT
        assert "rationale" in PLAN_SYSTEM_PROMPT
        assert "category" in PLAN_SYSTEM_PROMPT
        assert "files_affected" in PLAN_SYSTEM_PROMPT

    def test_prompt_includes_category_descriptions(self) -> None:
        """System prompt should describe decision categories."""
        from musonius.planning.prompts import PLAN_SYSTEM_PROMPT

        for category in ["architecture", "dependency", "pattern", "api", "security", "performance"]:
            assert category in PLAN_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 6. Go Command (CLI integration)
# ---------------------------------------------------------------------------


class TestGoCommand:
    """Tests for the musonius go one-command flow."""

    def test_go_registered_in_cli(self) -> None:
        """go command should be registered in the Typer app."""
        result = runner.invoke(app, ["go", "--help"])
        assert result.exit_code == 0
        assert "init" in result.output.lower() or "plan" in result.output.lower()

    def test_go_requires_task(self) -> None:
        """go should require a task argument."""
        result = runner.invoke(app, ["go"])
        assert result.exit_code != 0
