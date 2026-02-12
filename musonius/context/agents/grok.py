"""Grok agent plugin — generates markdown handoffs for xAI's Grok."""

from __future__ import annotations

from typing import Any

from musonius.context.agents.base import AgentCapabilities, AgentPlugin


class GrokPlugin(AgentPlugin):
    """Formats context for Grok using concise, direct markdown."""

    def capabilities(self) -> AgentCapabilities:
        """Return Grok capabilities."""
        return AgentCapabilities(
            name="Grok",
            slug="grok",
            file_extension=".md",
            file_name="GROK.md",
            supports_xml=False,
            supports_mermaid=False,
            supports_file_refs=True,
            supports_yolo=False,
            max_context_tokens=131_072,
            handoff_method="file",
            cli_command=None,
            description="xAI's Grok",
        )

    def format_context(
        self,
        task: str,
        plan: dict[str, Any],
        repo_map: str,
        memory: list[dict[str, str]],
        token_budget: int,
    ) -> str:
        """Format context as concise markdown for Grok.

        Args:
            task: Task description.
            plan: Structured plan dictionary.
            repo_map: Repository map string.
            memory: Relevant memory entries.
            token_budget: Maximum tokens for the output.

        Returns:
            Concise markdown handoff document.
        """
        sections: list[str] = []

        sections.append(f"# Task\n\n{task}")

        if memory:
            sections.append("# Project Knowledge")
            for entry in memory:
                if isinstance(entry, dict):
                    summary = entry.get("summary", "")
                    rationale = entry.get("rationale", "")
                    sections.append(f"- **{summary}** — {rationale}")

        if repo_map:
            sections.append(f"# Codebase Structure\n\n```\n{repo_map}\n```")

        if plan:
            phases = plan.get("phases", [])
            if phases:
                sections.append("# Implementation Plan")
                for i, phase in enumerate(phases, 1):
                    if isinstance(phase, dict):
                        title = phase.get("title", "Untitled")
                        desc = phase.get("description", "")
                        sections.append(f"## Step {i}: {title}\n\n{desc}")
                        files = phase.get("files", [])
                        if files:
                            sections.append("**Files:**")
                            for f in files:
                                if isinstance(f, dict):
                                    sections.append(
                                        f"- `{f.get('path', '')}`: {f.get('description', '')}"
                                    )
                        criteria = phase.get("acceptance_criteria", [])
                        if criteria:
                            sections.append("**Done when:**")
                            for c in criteria:
                                sections.append(f"- {c}")

        sections.append(
            "# Instructions\n\n"
            "Implement the changes above. Be direct and concise. "
            "Run tests after implementation."
        )

        return "\n\n".join(sections)
