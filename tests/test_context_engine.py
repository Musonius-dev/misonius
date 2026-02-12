"""Tests for the Context Engine (Layer 2) — full pipeline integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from musonius.context.budget import allocate_budget
from musonius.context.engine import ContextEngine, ContextResult
from musonius.context.indexer import Indexer
from musonius.context.repo_map import RepoMapGenerator
from musonius.memory.store import MemoryStore

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


# --- Fixtures ---


@pytest.fixture
def memory_store(tmp_path: Path) -> MemoryStore:
    """Create a fresh memory store with sample data."""
    db_path = tmp_path / "memory" / "decisions.db"
    store = MemoryStore(db_path)
    store.initialize()

    store.add_decision(
        summary="Use tree-sitter for AST parsing",
        rationale="Zero-cost local indexing without LLM tokens",
        category="architecture",
    )
    store.add_decision(
        summary="SQLite for memory storage",
        rationale="Embedded, zero-config, excellent for single-user CLI",
        category="dependency",
    )
    store.add_convention(
        pattern="naming",
        rule="Use snake_case for all Python identifiers",
        source="detected",
    )
    store.add_failure(
        approach="Using regex for code parsing",
        failure_reason="Cannot handle nested structures or context",
        alternative="tree-sitter AST parsing",
    )
    return store


@pytest.fixture
def indexer() -> Indexer:
    """Create an indexer pointed at the sample project."""
    return Indexer(FIXTURES_DIR)


@pytest.fixture
def repo_map_generator(indexer: Indexer) -> RepoMapGenerator:
    """Create a repo map generator with the sample project."""
    return RepoMapGenerator(indexer)


@pytest.fixture
def engine(
    indexer: Indexer,
    repo_map_generator: RepoMapGenerator,
    memory_store: MemoryStore,
) -> ContextEngine:
    """Create a fully wired context engine."""
    return ContextEngine(
        project_root=FIXTURES_DIR,
        indexer=indexer,
        repo_map_generator=repo_map_generator,
        memory_store=memory_store,
    )


@pytest.fixture
def sample_plan() -> dict[str, Any]:
    """Return a sample plan dictionary."""
    return {
        "epic_id": "epic-001",
        "task_description": "Add rate limiting to the API",
        "phases": [
            {
                "title": "Phase 1: Core Rate Limiter",
                "description": "Implement rate limiting middleware",
                "files": [
                    {"path": "main.py", "description": "Add rate limit decorator"},
                    {"path": "utils.py", "description": "Add token bucket algorithm"},
                ],
                "acceptance_criteria": ["Rate limit applied to all endpoints"],
            },
            {
                "title": "Phase 2: Configuration",
                "description": "Make rate limits configurable via `config.py`",
                "files": [
                    {"path": "config.py", "description": "Rate limit settings"},
                ],
                "acceptance_criteria": ["Config file parsed correctly"],
            },
        ],
    }


# --- BudgetAllocation Tests ---


class TestBudgetAllocation:
    """Tests for the budget allocation algorithm."""

    def test_small_budget_selects_l0(self) -> None:
        """Budget under 5K repo tokens should select L0."""
        alloc = allocate_budget(5000)
        assert alloc.detail_level == 0
        assert alloc.repo == 3500  # 70% of 5000

    def test_medium_budget_selects_l1(self) -> None:
        """Budget yielding 5K-15K repo tokens should select L1."""
        alloc = allocate_budget(15000)
        assert alloc.detail_level == 1
        assert alloc.repo == 10500

    def test_large_budget_selects_l2(self) -> None:
        """Budget yielding 15K-30K repo tokens should select L2."""
        alloc = allocate_budget(30000)
        assert alloc.detail_level == 2
        assert alloc.repo == 21000

    def test_very_large_budget_selects_l3(self) -> None:
        """Budget yielding 30K+ repo tokens should select L3."""
        alloc = allocate_budget(50000)
        assert alloc.detail_level == 3
        assert alloc.repo == 35000

    def test_budget_fractions(self) -> None:
        """Budget allocation should follow 10/15/5/70 split."""
        alloc = allocate_budget(10000)
        assert alloc.task == 1000
        assert alloc.plan == 1500
        assert alloc.memory == 500
        assert alloc.repo == 7000

    def test_budget_sums_to_total(self) -> None:
        """All allocations should sum to the total budget."""
        alloc = allocate_budget(10000)
        total = alloc.task + alloc.plan + alloc.memory + alloc.repo
        assert total == 10000

    def test_zero_budget(self) -> None:
        """Zero budget should produce all-zero allocation."""
        alloc = allocate_budget(0)
        assert alloc.task == 0
        assert alloc.plan == 0
        assert alloc.memory == 0
        assert alloc.repo == 0
        assert alloc.detail_level == 0

    def test_boundary_l0_l1(self) -> None:
        """Budget at the L0/L1 boundary (repo=5000)."""
        # repo = 70% of total, so total = 5000/0.7 ≈ 7143
        alloc = allocate_budget(7143)
        # repo = int(7143 * 0.7) = 5000
        assert alloc.repo == 5000
        assert alloc.detail_level == 1  # >= 5000 is L1

    def test_boundary_l1_l2(self) -> None:
        """Budget at the L1/L2 boundary (repo=15000)."""
        alloc = allocate_budget(21429)
        # repo = int(21429 * 0.7) = 15000
        assert alloc.repo == 15000
        assert alloc.detail_level == 2


# --- ContextEngine.get_context Tests ---


class TestGetContext:
    """Tests for the full get_context pipeline."""

    def test_returns_context_result(
        self, engine: ContextEngine, sample_plan: dict[str, Any]
    ) -> None:
        """get_context should return a ContextResult with all fields populated."""
        result = engine.get_context(
            task="Add rate limiting",
            plan=sample_plan,
            agent="claude",
            token_budget=10000,
        )
        assert isinstance(result, ContextResult)
        assert result.formatted_output != ""
        assert result.budget_allocation is not None
        assert result.token_count > 0

    def test_uses_agent_budget_when_none(self, engine: ContextEngine) -> None:
        """Should use agent's max_context_tokens when no budget is given."""
        result = engine.get_context(
            task="Simple task",
            agent="generic",
            token_budget=None,
        )
        # generic agent has 128K max context
        assert result.budget_allocation is not None
        assert result.budget_allocation.task + result.budget_allocation.plan + \
            result.budget_allocation.memory + result.budget_allocation.repo == 128_000

    def test_claude_format(
        self, engine: ContextEngine, sample_plan: dict[str, Any]
    ) -> None:
        """Claude agent output should contain XML tags."""
        result = engine.get_context(
            task="Add rate limiting",
            plan=sample_plan,
            agent="claude",
            token_budget=10000,
        )
        assert "<repo_map>" in result.formatted_output
        assert "Add rate limiting" in result.formatted_output

    def test_gemini_format(
        self, engine: ContextEngine, sample_plan: dict[str, Any]
    ) -> None:
        """Gemini agent output should use natural language format."""
        result = engine.get_context(
            task="Add rate limiting",
            plan=sample_plan,
            agent="gemini",
            token_budget=10000,
        )
        assert "# Task" in result.formatted_output
        assert "# Codebase Context" in result.formatted_output

    def test_generic_format(self, engine: ContextEngine) -> None:
        """Generic agent should produce plain markdown."""
        result = engine.get_context(
            task="Fix bug",
            agent="generic",
            token_budget=10000,
        )
        assert "# Task" in result.formatted_output

    def test_unknown_agent_raises(self, engine: ContextEngine) -> None:
        """Should raise KeyError for unknown agents."""
        with pytest.raises(KeyError, match="Unknown agent"):
            engine.get_context(task="test", agent="nonexistent", token_budget=1000)

    def test_includes_memory_decisions(
        self, engine: ContextEngine
    ) -> None:
        """Should include memory decisions in the result."""
        result = engine.get_context(
            task="tree-sitter",
            agent="claude",
            token_budget=10000,
        )
        assert len(result.memory_decisions) > 0
        summaries = [d["summary"] for d in result.memory_decisions]
        assert any("tree-sitter" in s for s in summaries)

    def test_includes_memory_conventions(
        self, engine: ContextEngine
    ) -> None:
        """Should include conventions in the result."""
        result = engine.get_context(
            task="anything",
            agent="claude",
            token_budget=10000,
        )
        assert len(result.memory_conventions) > 0

    def test_includes_memory_failures(
        self, engine: ContextEngine
    ) -> None:
        """Should include failure records in the result."""
        result = engine.get_context(
            task="code parsing",
            agent="claude",
            token_budget=10000,
        )
        assert len(result.memory_failures) > 0

    def test_empty_plan(self, engine: ContextEngine) -> None:
        """Should handle None and empty plans gracefully."""
        result = engine.get_context(
            task="General exploration",
            plan=None,
            agent="claude",
            token_budget=10000,
        )
        assert result.formatted_output != ""
        assert result.relevant_files == []

    def test_budget_allocation_populated(
        self, engine: ContextEngine
    ) -> None:
        """Budget allocation should be set in the result."""
        result = engine.get_context(
            task="test",
            agent="claude",
            token_budget=20000,
        )
        alloc = result.budget_allocation
        assert alloc is not None
        assert alloc.task == 2000
        assert alloc.plan == 3000
        assert alloc.memory == 1000
        assert alloc.repo == 14000
        assert alloc.detail_level == 1


# --- File Extraction Tests ---


class TestPlanFileExtraction:
    """Tests for extracting file references from plans."""

    def test_extracts_structured_files(
        self, engine: ContextEngine, sample_plan: dict[str, Any]
    ) -> None:
        """Should extract paths from structured file entries in phases."""
        files = engine._extract_plan_files(sample_plan)
        path_strs = [str(f) for f in files]
        assert "main.py" in path_strs
        assert "utils.py" in path_strs
        assert "config.py" in path_strs

    def test_extracts_files_from_description(
        self, engine: ContextEngine
    ) -> None:
        """Should extract backtick-quoted .py paths from descriptions."""
        plan = {
            "phases": [
                {
                    "title": "Phase 1",
                    "description": "Modify `src/auth.py` and `src/middleware.py`",
                    "files": [],
                }
            ]
        }
        files = engine._extract_plan_files(plan)
        path_strs = [str(f) for f in files]
        assert "src/auth.py" in path_strs
        assert "src/middleware.py" in path_strs

    def test_deduplicates_files(self, engine: ContextEngine) -> None:
        """Should not return duplicate paths."""
        plan = {
            "phases": [
                {
                    "title": "Phase 1",
                    "description": "Modify `main.py`",
                    "files": [{"path": "main.py", "description": "Update"}],
                },
                {
                    "title": "Phase 2",
                    "description": "Also touch `main.py`",
                    "files": [{"path": "main.py", "description": "Finalize"}],
                },
            ]
        }
        files = engine._extract_plan_files(plan)
        path_strs = [str(f) for f in files]
        assert path_strs.count("main.py") == 1

    def test_handles_string_file_entries(self, engine: ContextEngine) -> None:
        """Should handle plain string file entries."""
        plan = {
            "phases": [
                {
                    "title": "Phase 1",
                    "description": "",
                    "files": ["app.py", "models.py"],
                }
            ]
        }
        files = engine._extract_plan_files(plan)
        path_strs = [str(f) for f in files]
        assert "app.py" in path_strs
        assert "models.py" in path_strs

    def test_empty_plan_returns_empty(self, engine: ContextEngine) -> None:
        """Should return empty list for empty plan."""
        assert engine._extract_plan_files({}) == []
        assert engine._extract_plan_files({"phases": []}) == []


# --- Memory Integration Tests ---


class TestMemoryIntegration:
    """Tests for memory queries through the engine."""

    def test_builds_memory_entries_with_decisions(
        self, engine: ContextEngine
    ) -> None:
        """Decision entries should have summary and rationale."""
        decisions = [{"summary": "Use SQLite", "rationale": "Simple and embedded"}]
        entries = engine._build_memory_entries(decisions, [], [], 10000)
        assert len(entries) == 1
        assert entries[0]["summary"] == "Use SQLite"
        assert entries[0]["category"] == "decision"

    def test_builds_memory_entries_with_conventions(
        self, engine: ContextEngine
    ) -> None:
        """Convention entries should have formatted summary."""
        conventions = [{"pattern": "naming", "rule": "snake_case", "source": "detected"}]
        entries = engine._build_memory_entries([], conventions, [], 10000)
        assert len(entries) == 1
        assert "[naming]" in entries[0]["summary"]
        assert "snake_case" in entries[0]["summary"]
        assert entries[0]["category"] == "convention"

    def test_builds_memory_entries_with_failures(
        self, engine: ContextEngine
    ) -> None:
        """Failure entries should be prefixed with AVOID."""
        failures = [
            {
                "approach": "regex parsing",
                "failure_reason": "too fragile",
                "alternative": "tree-sitter",
            }
        ]
        entries = engine._build_memory_entries([], [], failures, 10000)
        assert len(entries) == 1
        assert "AVOID" in entries[0]["summary"]
        assert "tree-sitter" in entries[0]["rationale"]
        assert entries[0]["category"] == "failure"

    def test_memory_budget_truncation(self, engine: ContextEngine) -> None:
        """Should truncate memory entries when budget is exceeded."""
        # Create many entries that exceed a tiny budget
        decisions = [
            {"summary": f"Decision {i} with details", "rationale": "Long rationale text " * 10}
            for i in range(50)
        ]
        entries = engine._build_memory_entries(decisions, [], [], 100)
        assert len(entries) < 50

    def test_combined_memory_ordering(self, engine: ContextEngine) -> None:
        """Decisions should come before conventions before failures."""
        decisions = [{"summary": "D1", "rationale": "R1"}]
        conventions = [{"pattern": "p", "rule": "r", "source": "s"}]
        failures = [{"approach": "A1", "failure_reason": "F1", "alternative": ""}]
        entries = engine._build_memory_entries(decisions, conventions, failures, 10000)
        assert len(entries) == 3
        assert entries[0]["category"] == "decision"
        assert entries[1]["category"] == "convention"
        assert entries[2]["category"] == "failure"


# --- gather_context (Low-Level API) Tests ---


class TestGatherContext:
    """Tests for the low-level gather_context method."""

    def test_returns_context_result(self, engine: ContextEngine) -> None:
        """Should return a valid ContextResult."""
        result = engine.gather_context("Test task", token_budget=8000)
        assert isinstance(result, ContextResult)
        assert result.repo_map != ""
        assert result.budget_allocation is not None

    def test_prioritizes_relevant_files(self, engine: ContextEngine) -> None:
        """Relevant files should appear in the result."""
        result = engine.gather_context(
            "Test task",
            relevant_files=[Path("main.py")],
            token_budget=8000,
        )
        assert Path("main.py") in result.relevant_files

    def test_respects_detail_level(self, engine: ContextEngine) -> None:
        """Detail level should be reflected in the result."""
        result = engine.gather_context("Test task", token_budget=8000, detail_level=2)
        assert result.detail_level == 2

    def test_queries_memory(self, engine: ContextEngine) -> None:
        """Should populate memory fields from the store."""
        result = engine.gather_context("tree-sitter", token_budget=8000)
        assert len(result.memory_decisions) > 0
        assert len(result.memory_conventions) > 0


# --- Edge Cases ---


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_engine_with_no_memory(
        self, indexer: Indexer, repo_map_generator: RepoMapGenerator, tmp_path: Path
    ) -> None:
        """Engine should work even when memory store has no data."""
        db_path = tmp_path / "empty.db"
        empty_store = MemoryStore(db_path)
        empty_store.initialize()

        engine = ContextEngine(
            project_root=FIXTURES_DIR,
            indexer=indexer,
            repo_map_generator=repo_map_generator,
            memory_store=empty_store,
        )
        result = engine.get_context(
            task="Test task",
            agent="claude",
            token_budget=10000,
        )
        assert result.formatted_output != ""
        assert result.memory_decisions == []
        assert result.memory_conventions == []
        assert result.memory_failures == []

    def test_tiny_budget(self, engine: ContextEngine) -> None:
        """Should handle very small budgets without crashing."""
        result = engine.get_context(
            task="test",
            agent="claude",
            token_budget=100,
        )
        assert result.formatted_output != ""
        assert result.budget_allocation is not None
        assert result.budget_allocation.detail_level == 0

    def test_plan_with_non_dict_phases(self, engine: ContextEngine) -> None:
        """Should handle malformed plan phases gracefully."""
        plan: dict[str, Any] = {"phases": ["string phase", 42, None]}
        files = engine._extract_plan_files(plan)
        assert files == []

    def test_plan_with_empty_files(self, engine: ContextEngine) -> None:
        """Should handle phases with empty files lists."""
        plan: dict[str, Any] = {
            "phases": [{"title": "P1", "description": "", "files": []}]
        }
        files = engine._extract_plan_files(plan)
        assert files == []
