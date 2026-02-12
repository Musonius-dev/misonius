"""Custom agent plugin — loads agent definitions from YAML files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from musonius.context.agents.base import AgentCapabilities, AgentPlugin

logger = logging.getLogger(__name__)


class CustomAgentPlugin(AgentPlugin):
    """Agent plugin loaded from a YAML definition file.

    Supports custom templates (prepend/append), inherits formatting
    from a base plugin, and allows user-defined capabilities.

    Expected YAML format::

        name: "Roo Code"
        slug: "roo-code"
        description: "Roo Code VS Code extension"
        file_name: "AGENTS.md"
        format: "generic"

        preferences:
          use_xml: false
          use_mermaid: true
          max_tokens: 128000
          include_test_examples: true

        handoff:
          method: "file"
          command: null
          output_path: ".roo/"

        templates:
          prepend: |
            You are working on a Python project.
          append: |
            When done, create a summary of changes.
    """

    def __init__(self, yaml_path: Path) -> None:
        """Load agent configuration from a YAML file.

        Args:
            yaml_path: Path to the YAML definition file.

        Raises:
            ValueError: If the YAML is missing required fields.
        """
        self._yaml_path = yaml_path
        self._config = self._load_config(yaml_path)
        self._base_plugin: AgentPlugin | None = None

    @staticmethod
    def _load_config(yaml_path: Path) -> dict[str, Any]:
        """Load and validate the YAML configuration.

        Args:
            yaml_path: Path to the YAML file.

        Returns:
            Parsed configuration dictionary.

        Raises:
            ValueError: If required fields are missing.
            yaml.YAMLError: If the YAML is malformed.
        """
        content = yaml_path.read_text(encoding="utf-8")
        config = yaml.safe_load(content)
        if not isinstance(config, dict):
            msg = f"Expected YAML dict in {yaml_path}, got {type(config).__name__}"
            raise ValueError(msg)

        required = ("name", "slug")
        for field in required:
            if field not in config:
                msg = f"Missing required field '{field}' in {yaml_path}"
                raise ValueError(msg)

        return config

    def _get_base_plugin(self) -> AgentPlugin:
        """Get the base plugin to inherit formatting from.

        Lazily resolved to avoid circular imports.

        Returns:
            The base AgentPlugin instance.
        """
        if self._base_plugin is None:
            from musonius.context.agents.registry import create_default_registry

            registry = create_default_registry()
            format_type = self._config.get("format", "generic")
            try:
                self._base_plugin = registry.get(format_type)
            except KeyError:
                logger.warning(
                    "Unknown base format '%s' in %s, falling back to generic",
                    format_type,
                    self._yaml_path,
                )
                self._base_plugin = registry.get("generic")
        return self._base_plugin

    def capabilities(self) -> AgentCapabilities:
        """Return capabilities derived from the YAML configuration."""
        prefs = self._config.get("preferences", {})
        handoff = self._config.get("handoff", {})

        return AgentCapabilities(
            name=self._config["name"],
            slug=self._config["slug"],
            file_extension=".md",
            file_name=self._config.get("file_name", "AGENTS.md"),
            supports_xml=prefs.get("use_xml", False),
            supports_mermaid=prefs.get("use_mermaid", False),
            supports_file_refs=True,
            supports_yolo=False,
            max_context_tokens=prefs.get("max_tokens", 128_000),
            handoff_method=handoff.get("method", "file"),
            cli_command=handoff.get("command"),
            description=self._config.get("description", "Custom agent"),
        )

    def format_context(
        self,
        task: str,
        plan: dict[str, Any],
        repo_map: str,
        memory: list[dict[str, str]],
        token_budget: int,
    ) -> str:
        """Format context using the base plugin with custom templates applied.

        Args:
            task: Task description.
            plan: Structured plan dictionary.
            repo_map: Repository map string.
            memory: Relevant memory entries.
            token_budget: Maximum tokens for the output.

        Returns:
            Formatted handoff document with custom templates.
        """
        base = self._get_base_plugin()
        base_context = base.format_context(task, plan, repo_map, memory, token_budget)

        templates = self._config.get("templates", {})
        prepend = templates.get("prepend", "").strip()
        append = templates.get("append", "").strip()

        parts: list[str] = []
        if prepend:
            parts.append(prepend)
        parts.append(base_context)
        if append:
            parts.append(append)

        return "\n\n".join(parts)
