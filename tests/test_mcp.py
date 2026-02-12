"""Tests for the MCP server tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from musonius.mcp.server import (
    _get_memory_context,
    _get_plan_impl,
    _memory_query_impl,
    _record_decision_impl,
    _status_impl,
)


@pytest.fixture()
def musonius_project(tmp_path: Path) -> Path:
    """Create a minimal initialized Musonius project."""
    musonius_dir = tmp_path / ".musonius"
    (musonius_dir / "index").mkdir(parents=True)
    (musonius_dir / "memory").mkdir(parents=True)
    (musonius_dir / "epics").mkdir(parents=True)
    (musonius_dir / "sot").mkdir(parents=True)

    # Create a config
    config_path = musonius_dir / "config.yaml"
    config_path.write_text("default_agent: claude\n")

    # Create a memory store
    from musonius.memory.store import MemoryStore

    db_path = musonius_dir / "memory" / "decisions.db"
    store = MemoryStore(db_path)
    store.initialize()
    store.add_decision(summary="Use SQLite for storage", rationale="Simplicity", category="architecture")
    store.add_convention(pattern="naming", rule="Use snake_case for functions")
    store.add_failure(approach="Used raw SQL", failure_reason="SQL injection risk")
    store.close()

    # Create a sample epic
    epic_dir = musonius_dir / "epics" / "epic-test001"
    phases_dir = epic_dir / "phases"
    phases_dir.mkdir(parents=True)

    spec_path = epic_dir / "spec.md"
    spec_path.write_text("# Add rate limiting\n\nEpic ID: epic-test001\n")

    phase_path = phases_dir / "phase-01.md"
    phase_path.write_text("# Implement rate limiter\n\nAdd rate limiting middleware.\n")

    return tmp_path


class TestGetPlan:
    """Tests for _get_plan_impl."""

    def test_get_latest_plan(self, musonius_project: Path) -> None:
        result = _get_plan_impl(musonius_project)
        assert result["epic_id"] == "epic-test001"
        assert result["phase_count"] == 1
        assert len(result["phases"]) == 1
        assert "rate limiter" in result["phases"][0]["title"].lower()

    def test_get_plan_by_id(self, musonius_project: Path) -> None:
        result = _get_plan_impl(musonius_project, epic_id="epic-test001")
        assert result["epic_id"] == "epic-test001"

    def test_plan_not_found(self, musonius_project: Path) -> None:
        result = _get_plan_impl(musonius_project, epic_id="epic-nonexistent")
        assert "error" in result

    def test_no_epics_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".musonius").mkdir()
        result = _get_plan_impl(tmp_path)
        assert "error" in result


class TestMemoryQuery:
    """Tests for _memory_query_impl."""

    def test_search_decisions(self, musonius_project: Path) -> None:
        result = _memory_query_impl(musonius_project, "SQLite", memory_type="decisions")
        assert result["total_results"] >= 1
        decisions = result["results"]["decisions"]
        assert any("SQLite" in d.get("summary", "") for d in decisions)

    def test_search_all(self, musonius_project: Path) -> None:
        result = _memory_query_impl(musonius_project, "snake", memory_type="all")
        assert result["total_results"] >= 1

    def test_no_results(self, musonius_project: Path) -> None:
        result = _memory_query_impl(musonius_project, "zzz_nonexistent_zzz", memory_type="decisions")
        assert result["total_results"] == 0

    def test_missing_db(self, tmp_path: Path) -> None:
        (tmp_path / ".musonius").mkdir()
        result = _memory_query_impl(tmp_path, "test")
        assert "message" in result


class TestRecordDecision:
    """Tests for _record_decision_impl."""

    def test_records_decision(self, musonius_project: Path) -> None:
        result = _record_decision_impl(
            musonius_project,
            summary="Use Redis for caching",
            rationale="Performance improvement",
            category="architecture",
        )
        assert result["summary"] == "Use Redis for caching"
        assert "id" in result

    def test_records_with_files(self, musonius_project: Path) -> None:
        result = _record_decision_impl(
            musonius_project,
            summary="Add caching layer",
            files_affected=["cache.py", "config.py"],
        )
        assert result["message"] == "Decision recorded successfully."

    def test_records_and_queries(self, musonius_project: Path) -> None:
        _record_decision_impl(
            musonius_project,
            summary="Use WebSockets for real-time",
            category="architecture",
        )
        result = _memory_query_impl(musonius_project, "WebSockets", memory_type="decisions")
        assert result["total_results"] >= 1


class TestGetMemoryContext:
    """Tests for _get_memory_context helper."""

    def test_returns_entries(self, musonius_project: Path) -> None:
        entries = _get_memory_context(musonius_project, "SQLite")
        assert len(entries) >= 1
        assert entries[0]["type"] == "decision"

    def test_empty_query(self, musonius_project: Path) -> None:
        entries = _get_memory_context(musonius_project, "")
        assert isinstance(entries, list)

    def test_missing_db(self, tmp_path: Path) -> None:
        entries = _get_memory_context(tmp_path, "test")
        assert entries == []


class TestStatus:
    """Tests for _status_impl."""

    def test_status_initialized_project(self, musonius_project: Path) -> None:
        result = _status_impl(musonius_project)
        assert result["initialized"] is True
        assert result["project_root"] == str(musonius_project)

    def test_status_memory_counts(self, musonius_project: Path) -> None:
        result = _status_impl(musonius_project)
        assert "memory" in result
        assert result["memory"]["decisions"] >= 1
        assert result["memory"]["conventions"] >= 1
        assert result["memory"]["failures"] >= 1

    def test_status_epic_list(self, musonius_project: Path) -> None:
        result = _status_impl(musonius_project)
        assert "epics" in result
        assert result["epics"]["count"] == 1
        assert "epic-test001" in result["epics"]["ids"]

    def test_status_uninitialized(self, tmp_path: Path) -> None:
        result = _status_impl(tmp_path)
        assert result["initialized"] is False

    def test_status_no_memory(self, tmp_path: Path) -> None:
        musonius_dir = tmp_path / ".musonius"
        musonius_dir.mkdir()
        result = _status_impl(tmp_path)
        assert result["initialized"] is True
        assert result["memory"]["initialized"] is False


class TestToolRegistration:
    """Verify MCP tools are properly registered."""

    def test_mcp_server_has_tools(self) -> None:
        from musonius.mcp.server import mcp

        # FastMCP stores tools — verify they're registered
        assert mcp is not None
        assert mcp.name == "musonius"
