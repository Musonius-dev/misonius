"""Agent plugin registry — discovers and manages agent plugins."""

from __future__ import annotations

import logging
from pathlib import Path

from musonius.context.agents.base import AgentCapabilities, AgentPlugin

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry of available agent plugins.

    Plugins are registered by slug and can be retrieved by name.
    Discovery priority (highest to lowest):

    1. Project YAML (.musonius/agents/*.yaml)
    2. User YAML (~/.musonius/agents/*.yaml)
    3. Built-in Python plugins
    """

    def __init__(self) -> None:
        self._plugins: dict[str, AgentPlugin] = {}

    def register(self, plugin: AgentPlugin) -> None:
        """Register an agent plugin.

        If a plugin with the same slug already exists, it is replaced.

        Args:
            plugin: The agent plugin instance to register.
        """
        caps = plugin.capabilities()
        self._plugins[caps.slug] = plugin
        logger.debug("Registered agent plugin: %s", caps.slug)

    def get(self, slug: str) -> AgentPlugin:
        """Get an agent plugin by slug.

        Args:
            slug: Agent identifier (e.g., "claude", "gemini").

        Returns:
            The agent plugin instance.

        Raises:
            KeyError: If no plugin is registered with that slug.
        """
        if slug not in self._plugins:
            available = ", ".join(sorted(self._plugins.keys()))
            raise KeyError(
                f"Unknown agent '{slug}'. Available agents: {available or 'none registered'}"
            )
        return self._plugins[slug]

    def list_agents(self) -> list[str]:
        """List all registered agent slugs.

        Returns:
            Sorted list of agent slug strings.
        """
        return sorted(self._plugins.keys())

    def list_capabilities(self) -> list[AgentCapabilities]:
        """Return capabilities for all registered plugins.

        Returns:
            List of AgentCapabilities, sorted by slug.
        """
        return [self._plugins[slug].capabilities() for slug in sorted(self._plugins)]

    def __contains__(self, slug: str) -> bool:
        return slug in self._plugins


def create_default_registry() -> AgentRegistry:
    """Create a registry with all built-in agent plugins.

    Returns:
        AgentRegistry populated with default plugins.
    """
    from musonius.context.agents.claude import ClaudePlugin
    from musonius.context.agents.cursor import CursorPlugin
    from musonius.context.agents.gemini import GeminiPlugin
    from musonius.context.agents.generic import GenericPlugin
    from musonius.context.agents.grok import GrokPlugin

    registry = AgentRegistry()
    registry.register(ClaudePlugin())
    registry.register(GeminiPlugin())
    registry.register(GrokPlugin())
    registry.register(CursorPlugin())
    registry.register(GenericPlugin())
    return registry


def create_full_registry(project_root: Path | None = None) -> AgentRegistry:
    """Create a registry with built-in plugins and custom YAML agents.

    Discovery priority (last registered wins for same slug):

    1. Built-in Python plugins (lowest priority)
    2. User YAML (~/.musonius/agents/*.yaml)
    3. Project YAML (.musonius/agents/*.yaml) (highest priority)

    Args:
        project_root: Path to the project root. If None, uses cwd.

    Returns:
        AgentRegistry with all discovered plugins.
    """
    registry = create_default_registry()

    # User-level custom agents
    user_agents_dir = Path.home() / ".musonius" / "agents"
    _load_yaml_agents(registry, user_agents_dir)

    # Project-level custom agents (override user-level)
    if project_root is None:
        project_root = Path.cwd()
    project_agents_dir = project_root / ".musonius" / "agents"
    _load_yaml_agents(registry, project_agents_dir)

    return registry


def _load_yaml_agents(registry: AgentRegistry, agents_dir: Path) -> None:
    """Load custom agent plugins from YAML files in a directory.

    Args:
        registry: Registry to load plugins into.
        agents_dir: Directory containing *.yaml agent definitions.
    """
    if not agents_dir.is_dir():
        return

    from musonius.context.agents.custom import CustomAgentPlugin

    for yaml_path in sorted(agents_dir.glob("*.yaml")):
        try:
            plugin = CustomAgentPlugin(yaml_path)
            registry.register(plugin)
            logger.debug("Loaded custom agent from %s", yaml_path)
        except Exception:
            logger.warning("Failed to load custom agent from %s", yaml_path, exc_info=True)
