"""Activity logging helper — wraps CLI commands with persistent tracking."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from musonius.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Module-level session ID — unique per process invocation
_SESSION_ID: str = ""


def get_session_id() -> str:
    """Get or create the current session ID.

    Returns:
        Session ID string, unique per CLI invocation.
    """
    global _SESSION_ID
    if not _SESSION_ID:
        _SESSION_ID = f"s-{uuid.uuid4().hex[:12]}"
    return _SESSION_ID


def _get_store(project_root: Path) -> MemoryStore | None:
    """Safely get a memory store instance.

    Args:
        project_root: Project root directory.

    Returns:
        MemoryStore or None if not available.
    """
    db_path = project_root / ".musonius" / "memory" / "decisions.db"
    if not db_path.parent.exists():
        return None
    try:
        store = MemoryStore(db_path)
        store.initialize()
        return store
    except Exception as e:
        logger.debug("Could not open memory store: %s", e)
        return None


@contextmanager
def track_activity(
    project_root: Path,
    command: str,
    args: str = "",
    epic_id: str | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Context manager that tracks a CLI command's execution in the activity log.

    Usage:
        with track_activity(root, "plan", args="add rate limiting") as ctx:
            # do work...
            ctx["epic_id"] = plan.epic_id
            ctx["outcome"] = "Generated 3 phases"

    Args:
        project_root: Project root directory.
        command: Command name.
        args: Command arguments string.
        epic_id: Associated epic ID (can also be set via context dict).

    Yields:
        Mutable context dict. Set "outcome", "epic_id" during execution.
    """
    session_id = get_session_id()
    ctx: dict[str, Any] = {
        "session_id": session_id,
        "epic_id": epic_id,
        "outcome": "",
        "activity_id": None,
    }
    start = time.monotonic()

    store = _get_store(project_root)
    if store:
        try:
            ctx["activity_id"] = store.log_activity(
                session_id=session_id,
                command=command,
                args=args,
                epic_id=epic_id,
                status="started",
            )
        except Exception as e:
            logger.debug("Failed to log activity start: %s", e)

    try:
        yield ctx
        status = "completed"
    except Exception:
        status = "failed"
        ctx["outcome"] = ctx.get("outcome") or "Command failed with error"
        raise
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        if store and ctx.get("activity_id"):
            try:
                store.update_activity(
                    activity_id=ctx["activity_id"],
                    status=status,
                    outcome=ctx.get("outcome", ""),
                    duration_ms=elapsed_ms,
                )
            except Exception as e:
                logger.debug("Failed to update activity: %s", e)

            # Close store connection
            try:
                store.close()
            except Exception:
                pass


def save_clarification(
    project_root: Path,
    question: str,
    answer: str,
    epic_id: str | None = None,
) -> None:
    """Save an intent clarification Q&A pair to session context.

    Args:
        project_root: Project root directory.
        question: The clarification question.
        answer: The user's answer.
        epic_id: Associated epic ID.
    """
    store = _get_store(project_root)
    if not store:
        return

    try:
        store.save_session_context(
            session_id=get_session_id(),
            context_type="clarification",
            key=question,
            value=answer,
            epic_id=epic_id,
        )
        store.close()
    except Exception as e:
        logger.debug("Failed to save clarification: %s", e)


def save_preference(
    project_root: Path,
    key: str,
    value: str,
) -> None:
    """Save a user preference to session context.

    Args:
        project_root: Project root directory.
        key: Preference name.
        value: Preference value.
    """
    store = _get_store(project_root)
    if not store:
        return

    try:
        store.save_session_context(
            session_id=get_session_id(),
            context_type="preference",
            key=key,
            value=value,
        )
        store.close()
    except Exception as e:
        logger.debug("Failed to save preference: %s", e)
