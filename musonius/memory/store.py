"""SQLite-backed persistent memory store for decisions, conventions, and failures."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    epic_id TEXT,
    category TEXT DEFAULT 'general',
    summary TEXT NOT NULL,
    rationale TEXT,
    files_affected TEXT,
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    epic_id TEXT,
    approach TEXT NOT NULL,
    failure_reason TEXT NOT NULL,
    alternative TEXT,
    files_affected TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    rule TEXT NOT NULL,
    source TEXT DEFAULT 'detected',
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class MemoryStore:
    """SQLite-backed persistent memory store.

    Stores architectural decisions, coding conventions, and
    records of failed approaches to prevent repeated mistakes.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create the database and tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Decisions ---

    def add_decision(
        self,
        summary: str,
        rationale: str = "",
        category: str = "general",
        epic_id: str | None = None,
        files_affected: list[str] | None = None,
        confidence: float = 1.0,
    ) -> int:
        """Record an architectural decision.

        Args:
            summary: Brief summary of the decision.
            rationale: Why this decision was made.
            category: Category (architecture, dependency, pattern).
            epic_id: Associated epic ID, if any.
            files_affected: List of affected file paths.
            confidence: Confidence score 0.0-1.0.

        Returns:
            ID of the newly created record.
        """
        conn = self._get_connection()
        files_json = ",".join(files_affected) if files_affected else None
        cursor = conn.execute(
            """INSERT INTO decisions (epic_id, category, summary, rationale, files_affected, confidence)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (epic_id, category, summary, rationale, files_json, confidence),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_decision(self, decision_id: int) -> dict[str, Any] | None:
        """Get a single decision by ID.

        Args:
            decision_id: The decision's primary key.

        Returns:
            Decision dict, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT id, epic_id, category, summary, rationale, files_affected, confidence, created_at
               FROM decisions WHERE id = ?""",
            (decision_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def delete_decision(self, decision_id: int) -> bool:
        """Delete a decision by ID.

        Args:
            decision_id: The decision's primary key.

        Returns:
            True if a row was deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM decisions WHERE id = ?", (decision_id,))
        conn.commit()
        return cursor.rowcount > 0

    def search_decisions(self, query: str) -> list[dict[str, Any]]:
        """Search decisions by keyword matching.

        Args:
            query: Search query string.

        Returns:
            List of matching decision dicts.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT id, epic_id, category, summary, rationale, files_affected, confidence, created_at
               FROM decisions
               WHERE summary LIKE ? OR rationale LIKE ? OR category LIKE ?
               ORDER BY created_at DESC""",
            (f"%{query}%", f"%{query}%", f"%{query}%"),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_all_decisions(self) -> list[dict[str, Any]]:
        """Get all recorded decisions.

        Returns:
            List of all decision dicts.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT id, epic_id, category, summary, rationale, files_affected, confidence, created_at
               FROM decisions ORDER BY created_at DESC"""
        )
        return [dict(row) for row in cursor.fetchall()]

    # --- Conventions ---

    def add_convention(
        self,
        pattern: str,
        rule: str,
        source: str = "detected",
        confidence: float = 1.0,
    ) -> int:
        """Record a coding convention.

        Args:
            pattern: Convention pattern type (naming, imports, testing).
            rule: The convention rule text.
            source: Where the convention was learned (detected, user, agents.md).
            confidence: Confidence score 0.0-1.0.

        Returns:
            ID of the newly created record.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """INSERT INTO conventions (pattern, rule, source, confidence)
               VALUES (?, ?, ?, ?)""",
            (pattern, rule, source, confidence),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_convention(self, convention_id: int) -> dict[str, Any] | None:
        """Get a single convention by ID.

        Args:
            convention_id: The convention's primary key.

        Returns:
            Convention dict, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT id, pattern, rule, source, confidence, created_at
               FROM conventions WHERE id = ?""",
            (convention_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def delete_convention(self, convention_id: int) -> bool:
        """Delete a convention by ID.

        Args:
            convention_id: The convention's primary key.

        Returns:
            True if a row was deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM conventions WHERE id = ?", (convention_id,))
        conn.commit()
        return cursor.rowcount > 0

    def get_all_conventions(self) -> list[dict[str, Any]]:
        """Get all recorded conventions.

        Returns:
            List of all convention dicts.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT id, pattern, rule, source, confidence, created_at
               FROM conventions ORDER BY created_at DESC"""
        )
        return [dict(row) for row in cursor.fetchall()]

    # --- Failures ---

    def add_failure(
        self,
        approach: str,
        failure_reason: str,
        alternative: str | None = None,
        epic_id: str | None = None,
        files_affected: list[str] | None = None,
    ) -> int:
        """Record a failed approach to prevent repeating it.

        Args:
            approach: Description of the approach that failed.
            failure_reason: Why it failed.
            alternative: Alternative approach that worked, if known.
            epic_id: Associated epic ID, if any.
            files_affected: List of affected file paths.

        Returns:
            ID of the newly created record.
        """
        conn = self._get_connection()
        files_json = ",".join(files_affected) if files_affected else None
        cursor = conn.execute(
            """INSERT INTO failures (epic_id, approach, failure_reason, alternative, files_affected)
               VALUES (?, ?, ?, ?, ?)""",
            (epic_id, approach, failure_reason, alternative, files_json),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_failure(self, failure_id: int) -> dict[str, Any] | None:
        """Get a single failure by ID.

        Args:
            failure_id: The failure's primary key.

        Returns:
            Failure dict, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT id, epic_id, approach, failure_reason, alternative, files_affected, created_at
               FROM failures WHERE id = ?""",
            (failure_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def delete_failure(self, failure_id: int) -> bool:
        """Delete a failure by ID.

        Args:
            failure_id: The failure's primary key.

        Returns:
            True if a row was deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM failures WHERE id = ?", (failure_id,))
        conn.commit()
        return cursor.rowcount > 0

    def get_all_failures(self) -> list[dict[str, Any]]:
        """Get all recorded failures.

        Returns:
            List of all failure dicts.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT id, epic_id, approach, failure_reason, alternative, files_affected, created_at
               FROM failures ORDER BY created_at DESC"""
        )
        return [dict(row) for row in cursor.fetchall()]

    def search_failures(self, query: str) -> list[dict[str, Any]]:
        """Search failures by keyword.

        Args:
            query: Search query string.

        Returns:
            List of matching failure dicts.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT id, epic_id, approach, failure_reason, alternative, files_affected, created_at
               FROM failures
               WHERE approach LIKE ? OR failure_reason LIKE ?
               ORDER BY created_at DESC""",
            (f"%{query}%", f"%{query}%"),
        )
        return [dict(row) for row in cursor.fetchall()]
