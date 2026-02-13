"""Tests for the planning engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from musonius.planning.engine import (
    PlanningEngine,
    _detect_dependency_cycle,
    estimate_phase_tokens,
)
from musonius.planning.prompts import build_plan_prompt
from musonius.planning.schemas import FileChange, Phase, Plan

# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestPlanSchemas:
    """Tests for Pydantic plan models."""

    def test_file_change(self) -> None:
        """Should create a FileChange."""
        fc = FileChange(
            path="src/auth.py",
            action="modify",
            description="Add rate limiting",
            key_changes=["Add RateLimiter class", "Integrate with middleware"],
        )
        assert fc.path == "src/auth.py"
        assert fc.action == "modify"
        assert len(fc.key_changes) == 2

    def test_file_change_defaults(self) -> None:
        """Should default key_changes to empty list."""
        fc = FileChange(path="x.py", action="create", description="New file")
        assert fc.key_changes == []

    def test_phase(self) -> None:
        """Should create a Phase with files and criteria."""
        phase = Phase(
            id="phase-1",
            title="Add Rate Limiting",
            description="Implement rate limiting for the public API.",
            files=[
                FileChange(path="src/auth.py", action="modify", description="Add limiter"),
            ],
            acceptance_criteria=["Rate limiting works", "Tests pass"],
            test_strategy="Unit tests + integration test",
        )
        assert phase.id == "phase-1"
        assert len(phase.files) == 1
        assert len(phase.acceptance_criteria) == 2

    def test_phase_defaults(self) -> None:
        """Should default optional fields."""
        phase = Phase(id="p1", title="T", description="D")
        assert phase.files == []
        assert phase.dependencies == []
        assert phase.acceptance_criteria == []
        assert phase.test_strategy == ""
        assert phase.estimated_tokens == 0

    def test_plan(self) -> None:
        """Should create a complete Plan."""
        plan = Plan(
            epic_id="epic-abc123",
            task_description="Add rate limiting to the API",
            phases=[
                Phase(
                    id="phase-1",
                    title="Core Implementation",
                    description="Build the rate limiter.",
                    files=[],
                    acceptance_criteria=["Rate limiter works"],
                ),
            ],
        )
        assert plan.epic_id == "epic-abc123"
        assert len(plan.phases) == 1
        assert plan.created_at is not None

    def test_plan_serialization(self) -> None:
        """Should serialize to and from JSON."""
        plan = Plan(
            epic_id="epic-test",
            task_description="Test task",
            phases=[],
        )
        json_str = plan.model_dump_json()
        restored = Plan.model_validate_json(json_str)
        assert restored.epic_id == "epic-test"


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


class TestPrompts:
    """Tests for prompt template building."""

    def test_build_plan_prompt(self) -> None:
        """Should build valid message list."""
        messages = build_plan_prompt(
            task_description="Add rate limiting",
            repo_map="src/api.py\n  def handle_request()",
            max_phases=2,
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "rate limiting" in messages[1]["content"].lower()
        assert "2" in messages[1]["content"]

    def test_prompt_with_empty_context(self) -> None:
        """Should handle empty context gracefully."""
        messages = build_plan_prompt(task_description="Do something")
        assert "no repo map" in messages[1]["content"].lower()

    def test_prompt_includes_failures(self) -> None:
        """Should include failures context."""
        messages = build_plan_prompt(
            task_description="Add auth",
            failures="- FAILED: JWT approach — too complex",
        )
        assert "JWT approach" in messages[1]["content"]

    def test_prompt_empty_failures_placeholder(self) -> None:
        """Should show placeholder when no failures."""
        messages = build_plan_prompt(task_description="Add auth")
        assert "no known failures" in messages[1]["content"].lower()


# ---------------------------------------------------------------------------
# Token estimation tests
# ---------------------------------------------------------------------------


class TestTokenEstimation:
    """Tests for the estimate_phase_tokens function."""

    def test_create_file_base(self) -> None:
        """Create file with no key_changes uses base tokens."""
        files = [FileChange(path="x.py", action="create", description="New")]
        tokens = estimate_phase_tokens(files)
        assert tokens == int(500 * 1.2)

    def test_create_file_with_changes(self) -> None:
        """Create file tokens scale with key_changes."""
        files = [
            FileChange(
                path="x.py",
                action="create",
                description="New",
                key_changes=["a", "b"],
            )
        ]
        tokens = estimate_phase_tokens(files)
        assert tokens == int((500 + 300 * 2) * 1.2)

    def test_modify_file(self) -> None:
        """Modify file with key_changes."""
        files = [
            FileChange(
                path="y.py",
                action="modify",
                description="Update",
                key_changes=["c"],
            )
        ]
        tokens = estimate_phase_tokens(files)
        assert tokens == int((200 + 200) * 1.2)

    def test_delete_file(self) -> None:
        """Delete file is flat cost."""
        files = [FileChange(path="z.py", action="delete", description="Remove")]
        tokens = estimate_phase_tokens(files)
        assert tokens == int(50 * 1.2)

    def test_mixed_files(self) -> None:
        """Multiple files of different actions."""
        files = [
            FileChange(path="a.py", action="create", description="N", key_changes=["x"]),
            FileChange(path="b.py", action="modify", description="M"),
            FileChange(path="c.py", action="delete", description="D"),
        ]
        expected = int(((500 + 300) + 200 + 50) * 1.2)
        assert estimate_phase_tokens(files) == expected

    def test_empty_files(self) -> None:
        """No files yields zero tokens."""
        assert estimate_phase_tokens([]) == 0


# ---------------------------------------------------------------------------
# Dependency cycle detection tests
# ---------------------------------------------------------------------------


class TestDependencyCycleDetection:
    """Tests for _detect_dependency_cycle."""

    def test_no_cycle(self) -> None:
        """Linear dependency chain should be valid."""
        phases = [
            Phase(id="p1", title="A", description="", dependencies=[]),
            Phase(id="p2", title="B", description="", dependencies=["p1"]),
            Phase(id="p3", title="C", description="", dependencies=["p2"]),
        ]
        assert _detect_dependency_cycle(phases) is None

    def test_direct_cycle(self) -> None:
        """Two phases depending on each other should be detected."""
        phases = [
            Phase(id="p1", title="A", description="", dependencies=["p2"]),
            Phase(id="p2", title="B", description="", dependencies=["p1"]),
        ]
        assert _detect_dependency_cycle(phases) is not None

    def test_indirect_cycle(self) -> None:
        """Three-node cycle should be detected."""
        phases = [
            Phase(id="p1", title="A", description="", dependencies=["p3"]),
            Phase(id="p2", title="B", description="", dependencies=["p1"]),
            Phase(id="p3", title="C", description="", dependencies=["p2"]),
        ]
        assert _detect_dependency_cycle(phases) is not None

    def test_self_cycle(self) -> None:
        """Phase depending on itself should be detected."""
        phases = [
            Phase(id="p1", title="A", description="", dependencies=["p1"]),
        ]
        assert _detect_dependency_cycle(phases) is not None

    def test_no_dependencies(self) -> None:
        """Phases with no dependencies should be fine."""
        phases = [
            Phase(id="p1", title="A", description=""),
            Phase(id="p2", title="B", description=""),
        ]
        assert _detect_dependency_cycle(phases) is None


# ---------------------------------------------------------------------------
# PlanningEngine tests
# ---------------------------------------------------------------------------


def _make_memory() -> MagicMock:
    """Create a mock MemoryStore."""
    memory = MagicMock()
    memory.search_decisions.return_value = []
    memory.get_all_conventions.return_value = []
    memory.search_failures.return_value = []
    return memory


def _make_router(response_json: dict) -> MagicMock:
    """Create a mock ModelRouter that returns a JSON response."""
    router = MagicMock()
    resp = MagicMock()
    resp.content = json.dumps(response_json)
    router.call_planner.return_value = resp
    return router


SAMPLE_PLAN_JSON = {
    "phases": [
        {
            "id": "phase-1",
            "title": "Add Rate Limiter",
            "description": "Implement rate limiting middleware.",
            "files": [
                {
                    "path": "src/middleware.py",
                    "action": "create",
                    "description": "Create rate limiter middleware",
                    "key_changes": [
                        "Add RateLimiter class",
                        "Add sliding window algorithm",
                    ],
                },
                {
                    "path": "src/app.py",
                    "action": "modify",
                    "description": "Wire up middleware",
                    "key_changes": ["Register rate limiter"],
                },
            ],
            "acceptance_criteria": [
                "Rate limiter rejects requests over threshold",
                "Tests cover happy path and rate-exceeded path",
            ],
            "test_strategy": "Unit test RateLimiter class, integration test middleware",
        }
    ]
}


class TestPlanningEngineParseResponse:
    """Tests for PlanningEngine._parse_plan_response."""

    def test_parse_valid_json(self, tmp_path: Path) -> None:
        """Should parse a valid JSON plan response."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = engine._parse_plan_response(
            json.dumps(SAMPLE_PLAN_JSON), "Add rate limiting"
        )
        assert plan.epic_id.startswith("epic-")
        assert len(plan.phases) == 1
        assert plan.phases[0].title == "Add Rate Limiter"
        assert len(plan.phases[0].files) == 2
        assert plan.phases[0].files[0].action == "create"
        assert plan.phases[0].estimated_tokens > 0
        assert plan.total_estimated_tokens > 0

    def test_parse_defaults_missing_fields(self, tmp_path: Path) -> None:
        """Should use defaults for missing optional fields."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        minimal = {"phases": [{"files": [{"path": "x.py"}]}]}
        plan = engine._parse_plan_response(json.dumps(minimal), "task")
        phase = plan.phases[0]
        assert phase.title == "Untitled Phase"
        assert phase.description == ""
        assert phase.files[0].action == "modify"


class TestPlanningEngineExtractJson:
    """Tests for PlanningEngine._extract_json."""

    def test_direct_json(self, tmp_path: Path) -> None:
        """Should parse raw JSON directly."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        result = engine._extract_json('{"phases": []}')
        assert result == {"phases": []}

    def test_json_in_code_block(self, tmp_path: Path) -> None:
        """Should extract JSON from markdown code block."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        text = 'Here is the plan:\n```json\n{"phases": [{"id": "p1"}]}\n```\nDone.'
        result = engine._extract_json(text)
        assert result == {"phases": [{"id": "p1"}]}

    def test_unparseable_returns_empty(self, tmp_path: Path) -> None:
        """Should return empty plan for totally unparseable text."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        result = engine._extract_json("This is not JSON at all")
        assert result == {"phases": []}

    def test_json_embedded_in_conversation(self, tmp_path: Path) -> None:
        """Should extract JSON from conversational Claude CLI response."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        text = (
            "Here's the implementation plan for your request:\n\n"
            '{"phases": [{"id": "phase-1", "title": "Setup"}], '
            '"architecture_decisions": []}\n\n'
            "Let me know if you'd like any changes!"
        )
        result = engine._extract_json(text)
        assert "phases" in result
        assert len(result["phases"]) == 1
        assert result["phases"][0]["id"] == "phase-1"

    def test_json_with_nested_braces(self, tmp_path: Path) -> None:
        """Should handle deeply nested JSON objects."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan_json = json.dumps({
            "phases": [{
                "id": "phase-1",
                "title": "Add auth",
                "files": [{"path": "auth.py", "action": "create", "description": "Auth module"}],
                "acceptance_criteria": ["Tests pass"],
            }],
            "architecture_decisions": [{"summary": "Use JWT", "rationale": "Standard"}],
        })
        text = f"Analysis complete.\n{plan_json}\nEnd of plan."
        result = engine._extract_json(text)
        assert len(result["phases"]) == 1
        assert len(result["architecture_decisions"]) == 1

    def test_prefers_plan_json_over_small_objects(self, tmp_path: Path) -> None:
        """Should prefer the JSON with 'phases' key over smaller JSON objects."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        text = (
            'Status: {"ok": true}\n'
            '{"phases": [{"id": "p1", "title": "Main"}]}\n'
            'Metadata: {"version": 2}'
        )
        result = engine._extract_json(text)
        assert "phases" in result
        assert result["phases"][0]["id"] == "p1"


class TestPlanningEngineValidation:
    """Tests for PlanningEngine.validate_plan."""

    def test_valid_plan(self, tmp_path: Path) -> None:
        """A complete plan should pass validation."""
        # Create the file that will be modified
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("# app")

        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="epic-test",
            task_description="Test",
            phases=[
                Phase(
                    id="p1",
                    title="Phase 1",
                    description="Do things",
                    files=[
                        FileChange(
                            path="src/new.py",
                            action="create",
                            description="New file",
                        ),
                        FileChange(
                            path="src/app.py",
                            action="modify",
                            description="Update app",
                        ),
                    ],
                    acceptance_criteria=["Works correctly"],
                    test_strategy="Run pytest",
                ),
            ],
        )
        errors = engine.validate_plan(plan)
        assert errors == []

    def test_empty_phases(self, tmp_path: Path) -> None:
        """Plan with no phases should fail."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(epic_id="e", task_description="t", phases=[])
        errors = engine.validate_plan(plan)
        assert any("no phases" in e.lower() for e in errors)

    def test_no_files(self, tmp_path: Path) -> None:
        """Phase with no files should fail."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="e",
            task_description="t",
            phases=[
                Phase(
                    id="p1",
                    title="Empty",
                    description="D",
                    acceptance_criteria=["ok"],
                    test_strategy="pytest",
                )
            ],
        )
        errors = engine.validate_plan(plan)
        assert any("no files" in e.lower() for e in errors)

    def test_no_acceptance_criteria(self, tmp_path: Path) -> None:
        """Phase with no acceptance criteria should fail."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="e",
            task_description="t",
            phases=[
                Phase(
                    id="p1",
                    title="No AC",
                    description="D",
                    files=[FileChange(path="x.py", action="create", description="N")],
                    test_strategy="pytest",
                )
            ],
        )
        errors = engine.validate_plan(plan)
        assert any("acceptance criteria" in e.lower() for e in errors)

    def test_no_test_strategy(self, tmp_path: Path) -> None:
        """Phase with no test strategy should fail."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="e",
            task_description="t",
            phases=[
                Phase(
                    id="p1",
                    title="No TS",
                    description="D",
                    files=[FileChange(path="x.py", action="create", description="N")],
                    acceptance_criteria=["ok"],
                )
            ],
        )
        errors = engine.validate_plan(plan)
        assert any("test strategy" in e.lower() for e in errors)

    def test_invalid_action(self, tmp_path: Path) -> None:
        """Invalid file action should fail."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="e",
            task_description="t",
            phases=[
                Phase(
                    id="p1",
                    title="Bad",
                    description="D",
                    files=[FileChange(path="x.py", action="rename", description="N")],
                    acceptance_criteria=["ok"],
                    test_strategy="pytest",
                )
            ],
        )
        errors = engine.validate_plan(plan)
        assert any("invalid action" in e.lower() for e in errors)

    def test_modify_nonexistent_file(self, tmp_path: Path) -> None:
        """Modifying a file that doesn't exist should fail."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="e",
            task_description="t",
            phases=[
                Phase(
                    id="p1",
                    title="Missing",
                    description="D",
                    files=[FileChange(path="nope.py", action="modify", description="U")],
                    acceptance_criteria=["ok"],
                    test_strategy="pytest",
                )
            ],
        )
        errors = engine.validate_plan(plan)
        assert any("does not exist" in e for e in errors)

    def test_invalid_dependency(self, tmp_path: Path) -> None:
        """Dependency referencing non-existent phase should fail."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="e",
            task_description="t",
            phases=[
                Phase(
                    id="p1",
                    title="Dangling dep",
                    description="D",
                    dependencies=["p99"],
                    files=[FileChange(path="x.py", action="create", description="N")],
                    acceptance_criteria=["ok"],
                    test_strategy="pytest",
                )
            ],
        )
        errors = engine.validate_plan(plan)
        assert any("invalid dependency" in e.lower() for e in errors)

    def test_circular_dependency(self, tmp_path: Path) -> None:
        """Circular dependencies should fail."""
        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="e",
            task_description="t",
            phases=[
                Phase(
                    id="p1",
                    title="A",
                    description="D",
                    dependencies=["p2"],
                    files=[FileChange(path="a.py", action="create", description="N")],
                    acceptance_criteria=["ok"],
                    test_strategy="pytest",
                ),
                Phase(
                    id="p2",
                    title="B",
                    description="D",
                    dependencies=["p1"],
                    files=[FileChange(path="b.py", action="create", description="N")],
                    acceptance_criteria=["ok"],
                    test_strategy="pytest",
                ),
            ],
        )
        errors = engine.validate_plan(plan)
        assert any("circular" in e.lower() for e in errors)


class TestPlanningEngineSavePlan:
    """Tests for PlanningEngine._save_plan."""

    def test_save_creates_files(self, tmp_path: Path) -> None:
        """Should create spec.md and phase markdown files."""
        (tmp_path / ".musonius" / "epics").mkdir(parents=True)

        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="epic-save01",
            task_description="Test save",
            phases=[
                Phase(
                    id="p1",
                    title="Phase One",
                    description="First phase.",
                    files=[
                        FileChange(
                            path="src/a.py",
                            action="create",
                            description="New file",
                            key_changes=["Add class A"],
                        ),
                    ],
                    acceptance_criteria=["A works"],
                    test_strategy="Unit tests",
                    estimated_tokens=720,
                ),
            ],
            total_estimated_tokens=720,
        )

        engine._save_plan(plan)

        epic_dir = tmp_path / ".musonius" / "epics" / "epic-save01"
        assert (epic_dir / "spec.md").exists()
        assert (epic_dir / "phases" / "phase-01.md").exists()

        spec = (epic_dir / "spec.md").read_text()
        assert "Test save" in spec
        assert "epic-save01" in spec
        assert "720" in spec

        phase_md = (epic_dir / "phases" / "phase-01.md").read_text()
        assert "Phase One" in phase_md
        assert "src/a.py" in phase_md
        assert "Add class A" in phase_md
        assert "A works" in phase_md
        assert "Unit tests" in phase_md

    def test_save_multiple_phases(self, tmp_path: Path) -> None:
        """Should save all phases as separate files."""
        (tmp_path / ".musonius" / "epics").mkdir(parents=True)

        engine = PlanningEngine(
            memory=_make_memory(),
            router=_make_router({}),
            project_root=tmp_path,
        )
        plan = Plan(
            epic_id="epic-multi",
            task_description="Multi-phase",
            phases=[
                Phase(id="p1", title="First", description="D1",
                      files=[FileChange(path="a.py", action="create", description="N")],
                      acceptance_criteria=["ok"], test_strategy="pytest"),
                Phase(id="p2", title="Second", description="D2",
                      files=[FileChange(path="b.py", action="create", description="N")],
                      acceptance_criteria=["ok"], test_strategy="pytest"),
                Phase(id="p3", title="Third", description="D3",
                      dependencies=["p1", "p2"],
                      files=[FileChange(path="c.py", action="create", description="N")],
                      acceptance_criteria=["ok"], test_strategy="pytest"),
            ],
        )

        engine._save_plan(plan)

        phases_dir = tmp_path / ".musonius" / "epics" / "epic-multi" / "phases"
        assert (phases_dir / "phase-01.md").exists()
        assert (phases_dir / "phase-02.md").exists()
        assert (phases_dir / "phase-03.md").exists()

        phase3 = (phases_dir / "phase-03.md").read_text()
        assert "Dependencies" in phase3
        assert "p1" in phase3
        assert "p2" in phase3


class TestPlanningEngineGeneratePlan:
    """Tests for the full generate_plan flow with mocked dependencies."""

    def test_generate_plan_basic(self, tmp_path: Path) -> None:
        """Should generate, parse, and save a plan."""
        (tmp_path / ".musonius" / "epics").mkdir(parents=True)

        memory = _make_memory()
        router = _make_router(SAMPLE_PLAN_JSON)

        engine = PlanningEngine(
            memory=memory, router=router, project_root=tmp_path
        )
        plan = engine.generate_plan("Add rate limiting")

        assert plan.epic_id.startswith("epic-")
        assert plan.task_description == "Add rate limiting"
        assert len(plan.phases) == 1
        assert plan.phases[0].title == "Add Rate Limiter"
        assert plan.total_estimated_tokens > 0

        # Verify memory was queried
        memory.search_decisions.assert_called_once_with("Add rate limiting")
        memory.get_all_conventions.assert_called_once()
        memory.search_failures.assert_called_once_with("Add rate limiting")

        # Verify router was called
        router.call_planner.assert_called_once()

        # Verify files were saved
        epics_dir = tmp_path / ".musonius" / "epics"
        saved_dirs = list(epics_dir.iterdir())
        assert len(saved_dirs) == 1
        assert (saved_dirs[0] / "spec.md").exists()

    def test_generate_plan_with_memory_context(self, tmp_path: Path) -> None:
        """Should include memory context in the prompt."""
        (tmp_path / ".musonius" / "epics").mkdir(parents=True)

        memory = _make_memory()
        memory.search_decisions.return_value = [
            {"summary": "Use FastAPI", "rationale": "Better async support"}
        ]
        memory.get_all_conventions.return_value = [
            {"pattern": "naming", "rule": "Use snake_case"}
        ]
        memory.search_failures.return_value = [
            {"approach": "Flask middleware", "failure_reason": "No async support"}
        ]

        router = _make_router(SAMPLE_PLAN_JSON)
        engine = PlanningEngine(
            memory=memory, router=router, project_root=tmp_path
        )
        engine.generate_plan("Add rate limiting")

        # Verify the prompt includes memory context
        call_args = router.call_planner.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "FastAPI" in user_msg
        assert "snake_case" in user_msg
        assert "Flask middleware" in user_msg

    def test_generate_plan_with_repo_map(self, tmp_path: Path) -> None:
        """Should include repo map in the prompt."""
        (tmp_path / ".musonius" / "epics").mkdir(parents=True)

        router = _make_router(SAMPLE_PLAN_JSON)
        engine = PlanningEngine(
            memory=_make_memory(), router=router, project_root=tmp_path
        )
        engine.generate_plan("Add auth", repo_map="src/app.py\n  def main()")

        call_args = router.call_planner.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "src/app.py" in user_msg
        assert "def main()" in user_msg

    def test_generate_plan_multi_phase(self, tmp_path: Path) -> None:
        """Should pass max_phases to the prompt."""
        (tmp_path / ".musonius" / "epics").mkdir(parents=True)

        multi_json = {
            "phases": [
                {
                    "id": "phase-1",
                    "title": "Schema",
                    "description": "DB schema",
                    "files": [{"path": "schema.py", "action": "create", "description": "Schema"}],
                    "acceptance_criteria": ["Schema created"],
                    "test_strategy": "pytest",
                },
                {
                    "id": "phase-2",
                    "title": "API",
                    "description": "API endpoints",
                    "dependencies": ["phase-1"],
                    "files": [{"path": "api.py", "action": "create", "description": "API"}],
                    "acceptance_criteria": ["API works"],
                    "test_strategy": "integration tests",
                },
            ]
        }

        router = _make_router(multi_json)
        engine = PlanningEngine(
            memory=_make_memory(), router=router, project_root=tmp_path
        )
        plan = engine.generate_plan("Add user auth", max_phases=3)

        assert len(plan.phases) == 2
        assert plan.phases[1].dependencies == ["phase-1"]

        # Check prompt includes max_phases
        call_args = router.call_planner.call_args
        messages = call_args[0][0]
        assert "3 phase(s)" in messages[1]["content"]
