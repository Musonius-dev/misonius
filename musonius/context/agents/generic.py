"""Generic agent plugin — produces AGENTS.md compatible with any tool."""

from __future__ import annotations

from typing import Any

from musonius.context.agents.base import AgentCapabilities, AgentPlugin


class GenericPlugin(AgentPlugin):
    """Formats context as plain markdown compatible with any AI coding tool."""

    def capabilities(self) -> AgentCapabilities:
        """Return generic agent capabilities."""
        return AgentCapabilities(
            name="Generic Agent",
            slug="generic",
            file_extension=".md",
            file_name="AGENTS.md",
            supports_xml=False,
            supports_mermaid=False,
            supports_file_refs=True,
            supports_yolo=False,
            max_context_tokens=128_000,
            handoff_method="file",
            cli_command=None,
            description="Universal markdown format",
        )

    def format_context(
        self,
        task: str,
        plan: dict[str, Any],
        repo_map: str,
        memory: list[dict[str, str]],
        token_budget: int,
    ) -> str:
        """Format context as plain AGENTS.md.

        Args:
            task: Task description.
            plan: Structured plan dictionary.
            repo_map: Repository map string.
            memory: Relevant memory entries.
            token_budget: Maximum tokens for the output.

        Returns:
            Plain markdown handoff document.
        """
        sections: list[str] = []

        sections.append(f"# Task\n\n{task}")

        if plan:
            phases = plan.get("phases", [])
            if phases:
                sections.append("# Plan")
                for phase in phases:
                    if isinstance(phase, dict):
                        title = phase.get("title", "Untitled")
                        desc = phase.get("description", "")
                        sections.append(f"## {title}\n\n{desc}")

        if repo_map:
            sections.append(f"# Repository Map\n\n```\n{repo_map}\n```")

        if memory:
            sections.append("# Context from Memory")
            for entry in memory:
                if isinstance(entry, dict):
                    sections.append(f"- {entry.get('summary', '')}")

        return "\n\n".join(sections)
