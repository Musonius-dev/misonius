"""musonius status — show project status, token usage, and progress."""

from __future__ import annotations

import logging

from musonius.cli.utils import handle_errors, require_initialized

logger = logging.getLogger(__name__)


@handle_errors
def status_command() -> None:
    """Show project status, token usage, and memory statistics.

    Displays a comprehensive dashboard with component health,
    model routing strategy, epic progress, and CLI tool availability.
    """
    project_root = require_initialized()

    from musonius.cli.display import render_status_dashboard

    render_status_dashboard(project_root)
