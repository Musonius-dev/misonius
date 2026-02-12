"""Tests for the memory store."""

from __future__ import annotations

from pathlib import Path

import pytest

from musonius.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    """Create a temporary memory store."""
    db_path = tmp_path / "test.db"
    s = MemoryStore(db_path)
    s.initialize()
    return s


class TestMemoryStore:
    """Tests for the MemoryStore class."""

    def test_initialize_creates_tables(self, store: MemoryStore) -> None:
        """Should create all required tables."""
        conn = store._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] for row in cursor.fetchall()]
        assert "decisions" in tables
        assert "conventions" in tables
        assert "failures" in tables

    def test_add_and_get_decisions(self, store: MemoryStore) -> None:
        """Should add and retrieve decisions."""
        store.add_decision(
            summary="Use SQLite for storage",
            rationale="Simple, no server needed",
            category="architecture",
        )
        decisions = store.get_all_decisions()
        assert len(decisions) == 1
        assert decisions[0]["summary"] == "Use SQLite for storage"
        assert decisions[0]["category"] == "architecture"

    def test_search_decisions(self, store: MemoryStore) -> None:
        """Should find decisions by keyword."""
        store.add_decision(summary="Use SQLite", rationale="Simple storage")
        store.add_decision(summary="Use Redis", rationale="Fast caching")

        results = store.search_decisions("SQLite")
        assert len(results) == 1
        assert results[0]["summary"] == "Use SQLite"

    def test_add_and_get_conventions(self, store: MemoryStore) -> None:
        """Should add and retrieve conventions."""
        store.add_convention(
            pattern="naming",
            rule="Use snake_case for functions",
            source="detected",
        )
        conventions = store.get_all_conventions()
        assert len(conventions) == 1
        assert conventions[0]["rule"] == "Use snake_case for functions"

    def test_add_and_get_failures(self, store: MemoryStore) -> None:
        """Should add and retrieve failures."""
        store.add_failure(
            approach="Used raw SQL",
            failure_reason="SQL injection vulnerability",
            alternative="Use parameterized queries",
        )
        failures = store.get_all_failures()
        assert len(failures) == 1
        assert "SQL injection" in failures[0]["failure_reason"]

    def test_search_failures(self, store: MemoryStore) -> None:
        """Should search failures by keyword."""
        store.add_failure(approach="Used eval()", failure_reason="Security risk")
        store.add_failure(approach="Used subprocess", failure_reason="Timeout issue")

        results = store.search_failures("eval")
        assert len(results) == 1

    def test_decision_with_files_affected(self, store: MemoryStore) -> None:
        """Should store affected files list."""
        store.add_decision(
            summary="Refactored auth",
            rationale="Cleaner code",
            files_affected=["auth.py", "models.py"],
        )
        decisions = store.get_all_decisions()
        assert "auth.py" in decisions[0]["files_affected"]

    def test_decision_confidence(self, store: MemoryStore) -> None:
        """Should store confidence scores."""
        store.add_decision(
            summary="Might use Redis",
            rationale="Not sure yet",
            confidence=0.5,
        )
        decisions = store.get_all_decisions()
        assert decisions[0]["confidence"] == 0.5
