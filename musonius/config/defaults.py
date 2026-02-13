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

def generate_optimal_models(
    cli_tools: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Generate optimal model config based on available CLI tools and API keys.

    Detects what the user actually has installed and maps each model role
    to a provider they can reach. This prevents the router from wasting
    time trying unavailable providers (e.g., gemini when only claude is installed).

    Args:
        cli_tools: Pre-detected CLI tools dict. Auto-detected if None.

    Returns:
        Model configuration dict mapping roles to model identifiers.
    """
    import os

    if cli_tools is None:
        from musonius.orchestration.cli_backend import detect_cli_tools

        cli_tools = detect_cli_tools()

    has_anthropic_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY"))
    has_claude_cli = "claude" in cli_tools
    has_gemini_cli = "gemini" in cli_tools

    # Start with defaults
    models: dict[str, str] = dict(DEFAULT_CONFIG["models"])

    # Claude-only user: remap all cheap roles to Anthropic
    if (has_claude_cli or has_anthropic_key) and not has_gemini_cli and not has_gemini_key:
        models["scout"] = "anthropic/claude-3-5-haiku-20241022"
        models["verifier"] = "anthropic/claude-3-5-haiku-20241022"
        models["summarizer"] = "anthropic/claude-3-5-haiku-20241022"

    # Gemini-only user: remap planner to Gemini
    if (has_gemini_cli or has_gemini_key) and not has_claude_cli and not has_anthropic_key:
        models["planner"] = "gemini/gemini-2.0-flash"

    # Both available: keep defaults (gemini for cheap ops, claude for planning)

    # API keys present: prefer API models for quality
    if has_anthropic_key:
        models["planner"] = DEFAULT_CONFIG["models"]["planner"]
    if has_gemini_key:
        models["scout"] = DEFAULT_CONFIG["models"]["scout"]
        models["verifier"] = DEFAULT_CONFIG["models"]["verifier"]

    return models


MUSONIUS_DIR = ".musonius"
CONFIG_FILE = "config.yaml"
INDEX_DIR = "index"
MEMORY_DIR = "memory"
EPICS_DIR = "epics"
SOT_DIR = "sot"
TEMPLATES_DIR = "templates"
