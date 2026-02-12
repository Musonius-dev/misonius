"""Default configuration values for Musonius."""

from __future__ import annotations

from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "models": {
        "scout": "gemini/gemini-2.0-flash",
        "planner": "anthropic/claude-sonnet-4-20250514",
        "verifier": "gemini/gemini-2.0-flash",
        "summarizer": "ollama/llama3.2",
    },
    "default_agent": "claude",
    "autonomy": {
        "level": 2,
        "max_retries": 3,
        "stop_on": "critical",
    },
    "budgets": {
        "plan": 8000,
        "verify": 6000,
        "prep": None,
    },
    "project": {
        "language": "python",
        "test_command": "pytest",
        "lint_command": "ruff check .",
    },
}

MUSONIUS_DIR = ".musonius"
CONFIG_FILE = "config.yaml"
INDEX_DIR = "index"
MEMORY_DIR = "memory"
EPICS_DIR = "epics"
SOT_DIR = "sot"
TEMPLATES_DIR = "templates"
