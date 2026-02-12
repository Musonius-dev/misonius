"""Gemini agent plugin — generates natural-language GEMINI.md handoffs."""

from __future__ import annotations

from typing import Any

from musonius.context.agents.base import AgentCapabilities, AgentPlugin


class GeminiPlugin(AgentPlugin):
    """Formats context for Gemini CLI using natural language markdown."""

    def capabilities(self) -> AgentCapabilities:
        """Return Gemini CLI capabilities."""
        return AgentCapabilities(
            name="Gemini CLI",
            slug="gemini",
            file_extension=".md",
            file_name="GEMINI.md",
            supports_xml=False,
            supports_mermaid=True,
            supports_file_refs=True,
            supports_yolo=True,
            max_context_tokens=1_000_000,
            handoff_method="file",
            cli_command="gemini --file {file}",
            description="Google's Gemini CLI",
        )

    def format_context(
        self,
        task: str,
        plan: dict[str, Any],
        repo_map: str,
        memory: list[dict[str, str]],
        token_budget: int,
    ) -> str:
        """Format context as natural-language GEMINI.md.

        Args:
            task: Task description.
            plan: Structured plan dictionary.
            repo_map: Repository map string.
            memory: Relevant memory entries.
            token_budget: Maximum tokens for the output.

        Returns:
            Natural-language markdown handoff document.
        """
        sections: list[str] = []

        sections.append(f"# Task\n\n{task}")

        if plan:
            phases = plan.get("phases", [])
            if phases:
                sections.append("# Implementation Plan")
                for i, phase in enumerate(phases, 1):
                    if isinstance(phase, dict):
                        title = phase.get("title", "Untitled")
                        desc = phase.get("description", "")
                        sections.append(f"## Phase {i}: {title}\n\n{desc}")
                        files = phase.get("files", [])
                        if files:
                            sections.append("**Files to change:**")
                            for f in files:
                                if isinstance(f, dict):
                                    sections.append(
                                        f"- {f.get('path', '')}: {f.get('description', '')}"
                                    )

        if repo_map:
            sections.append(f"# Codebase Context\n\n```\n{repo_map}\n```")

        if memory:
            sections.append("# Prior Decisions")
            for entry in memory:
                if isinstance(entry, dict):
                    summary = entry.get("summary", "")
                    rationale = entry.get("rationale", "")
                    sections.append(f"- {summary} — {rationale}")

        return "\n\n".join(sections)
