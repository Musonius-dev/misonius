"""Sample utility module for testing."""

import os
from pathlib import Path


def format_name(name: str) -> str:
    """Format a name for display."""
    return name.strip().title()


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(os.getcwd())
