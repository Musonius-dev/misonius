"""Agent plugins for format-specific context generation."""

from __future__ import annotations

from musonius.context.agents.base import AgentCapabilities, AgentPlugin
from musonius.context.agents.registry import (
    AgentRegistry,
    create_default_registry,
    create_full_registry,
)

__all__ = [
    "AgentCapabilities",
    "AgentPlugin",
    "AgentRegistry",
    "create_default_registry",
    "create_full_registry",
]
