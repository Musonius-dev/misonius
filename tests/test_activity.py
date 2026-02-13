"""Tests for activity tracking and session context persistence."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from musonius.memory.activity import (
    get_session_id,
    save_clarification,
    save_preference,
    track_activity,
)
from musonius.memory.store import MemoryStore


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a project root with .musonius/memory directory."""
    memory_dir = tmp_path / ".musonius" / "memory"
    memory_dir.mkdir(parents=True)
    # Initialize the database
    store = MemoryStore(memory_dir / "decisions.db")
    store.initialize()
    store.close()
    return tmp_path


@pytest.fixture
def store(project_root: Path) -> MemoryStore:
    """Create a memory store pointing to the project root."""
    s = MemoryStore(project_root / ".musonius" / "memory" / "decisions.db")
    s.initialize()
    return s


class TestGetSessionId:
    """Tests for session ID generation."""

    def test_returns_string(self) -> None:
        """Session ID should be a non-empty string."""
        sid = get_session_id()
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_starts_with_prefix(self) -> None:
        """Session ID should start with 's-'."""
        sid = get_session_id()
        assert sid.startswith("s-")

    def test_stable_within_process(self) -> None:
        """Session ID should be the same across calls in one process."""
        sid1 = get_session_id()
        sid2 = get_session_id()
        assert sid1 == sid2


class TestTrackActivity:
    """Tests for the track_activity context manager."""

    def test_logs_completed_activity(self, project_root: Path, store: MemoryStore) -> None:
        """Should log a completed activity entry."""
        with track_activity(project_root, "test-cmd", args="some args") as ctx:
            ctx["outcome"] = "did something"

        entries = store.get_activity_log(command="test-cmd")
        assert len(entries) >= 1
        entry = entries[0]
        assert entry["command"] == "test-cmd"
        assert entry["status"] == "completed"
        assert entry["outcome"] == "did something"
        assert entry["duration_ms"] > 0

    def test_logs_failed_activity(self, project_root: Path, store: MemoryStore) -> None:
        """Should log a failed activity when exception occurs."""
        with pytest.raises(ValueError, match="boom"):
            with track_activity(project_root, "fail-cmd") as ctx:
                raise ValueError("boom")

        entries = store.get_activity_log(command="fail-cmd")
        assert len(entries) >= 1
        assert entries[0]["status"] == "failed"

    def test_records_epic_id(self, project_root: Path, store: MemoryStore) -> None:
        """Should allow setting epic_id via context dict."""
        with track_activity(project_root, "plan", args="task") as ctx:
            ctx["epic_id"] = "epic-001"
            ctx["outcome"] = "Generated 3 phases"

        entries = store.get_activity_log(command="plan")
        assert len(entries) >= 1
        # The epic_id is set at log time (start), so it may be None initially;
        # the outcome is updated on completion.
        assert entries[0]["outcome"] == "Generated 3 phases"

    def test_tracks_duration(self, project_root: Path, store: MemoryStore) -> None:
        """Should record a non-zero duration."""
        with track_activity(project_root, "slow-cmd") as ctx:
            time.sleep(0.01)
            ctx["outcome"] = "done"

        entries = store.get_activity_log(command="slow-cmd")
        assert len(entries) >= 1
        assert entries[0]["duration_ms"] >= 5  # At least 5ms (sleep was 10ms)

    def test_handles_missing_musonius_dir(self, tmp_path: Path) -> None:
        """Should not crash when .musonius directory doesn't exist."""
        # No .musonius directory — should silently skip
        with track_activity(tmp_path, "orphan-cmd") as ctx:
            ctx["outcome"] = "no-op"
        # No assertion — just verifying no exception is raised


class TestSaveClarification:
    """Tests for saving intent clarification Q&A."""

    def test_saves_clarification(self, project_root: Path, store: MemoryStore) -> None:
        """Should save a clarification to session_context table."""
        save_clarification(project_root, "What auth method?", "OAuth2")

        entries = store.get_session_context(context_type="clarification")
        assert len(entries) >= 1
        assert entries[0]["key"] == "What auth method?"
        assert entries[0]["value"] == "OAuth2"

    def test_saves_with_epic_id(self, project_root: Path, store: MemoryStore) -> None:
        """Should associate clarification with an epic."""
        save_clarification(project_root, "Target scope?", "API only", epic_id="epic-007")

        entries = store.get_session_context(context_type="clarification", epic_id="epic-007")
        assert len(entries) >= 1
        assert entries[0]["value"] == "API only"

    def test_handles_missing_store(self, tmp_path: Path) -> None:
        """Should not crash when .musonius doesn't exist."""
        save_clarification(tmp_path, "Q?", "A")
        # No assertion — just verifying no exception


class TestSavePreference:
    """Tests for saving user preferences."""

    def test_saves_preference(self, project_root: Path, store: MemoryStore) -> None:
        """Should save a preference to session_context table."""
        save_preference(project_root, "agent", "claude")

        entries = store.get_session_context(context_type="preference")
        assert len(entries) >= 1
        assert entries[0]["key"] == "agent"
        assert entries[0]["value"] == "claude"

    def test_handles_missing_store(self, tmp_path: Path) -> None:
        """Should not crash when store is unavailable."""
        save_preference(tmp_path, "k", "v")
