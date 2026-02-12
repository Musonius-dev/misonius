"""Cursor agent plugin — generates .cursorrules handoff files for Cursor IDE."""

from __future__ import annotations

from typing import Any

from musonius.context.agents.base import AgentCapabilities, AgentPlugin


class CursorPlugin(AgentPlugin):
    """Formats context as .cursorrules for the Cursor IDE."""

    def capabilities(self) -> AgentCapabilities:
        """Return Cursor capabilities."""
        return AgentCapabilities(
            name="Cursor",
            slug="cursor",
            file_extension=".cursorrules",
            file_name=".cursorrules",
            supports_xml=False,
            supports_mermaid=False,
            supports_file_refs=True,
            supports_yolo=True,
            max_context_tokens=128_000,
            handoff_method="file",
            cli_command=None,
            description="Cursor AI IDE",
        )

    def format_context(
        self,
        task: str,
        plan: dict[str, Any],
        repo_map: str,
        memory: list[dict[str, str]],
        token_budget: int,
    ) -> str:
        """Format context as .cursorrules file content.

        Cursor uses a flat rules-style format. This plugin produces a
        structured rules file that Cursor can ingest as project context.

        Args:
            task: Task description.
            plan: Structured plan dictionary.
            repo_map: Repository map string.
            memory: Relevant memory entries.
            token_budget: Maximum tokens for the output.

        Returns:
            .cursorrules formatted handoff document.
        """
        sections: list[str] = []

        sections.append(f"# Current Task\n\n{task}")

        if memory:
            sections.append("# Project Conventions")
            for entry in memory:
                if isinstance(entry, dict):
                    summary = entry.get("summary", "")
                    rationale = entry.get("rationale", "")
                    if rationale:
                        sections.append(f"- {summary}: {rationale}")
                    else:
                        sections.append(f"- {summary}")

        if plan:
            phases = plan.get("phases", [])
            if phases:
                sections.append("# Implementation Steps")
                for i, phase in enumerate(phases, 1):
                    if isinstance(phase, dict):
                        title = phase.get("title", "Untitled")
                        desc = phase.get("description", "")
                        sections.append(f"\n## {i}. {title}\n\n{desc}")
                        files = phase.get("files", [])
                        if files:
                            for f in files:
                                if isinstance(f, dict):
                                    sections.append(
                                        f"- Modify `{f.get('path', '')}`: "
                                        f"{f.get('description', '')}"
                                    )
                        criteria = phase.get("acceptance_criteria", [])
                        if criteria:
                            sections.append("\nAcceptance criteria:")
                            for c in criteria:
                                sections.append(f"- [ ] {c}")

        if repo_map:
            sections.append(f"# Relevant Files\n\n```\n{repo_map}\n```")

        sections.append(
            "# Rules\n\n"
            "- Follow the implementation steps in order.\n"
            "- Only modify files listed in the plan.\n"
            "- Run tests after each step.\n"
            "- Do not refactor unrelated code."
        )

        return "\n\n".join(sections)
