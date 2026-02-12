"""Claude Code agent plugin — generates XML-structured CLAUDE.md handoffs."""

from __future__ import annotations

from typing import Any

from musonius.context.agents.base import AgentCapabilities, AgentPlugin


class ClaudePlugin(AgentPlugin):
    """Formats context for Claude Code using XML-structured markdown."""

    def capabilities(self) -> AgentCapabilities:
        """Return Claude Code capabilities."""
        return AgentCapabilities(
            name="Claude Code",
            slug="claude",
            file_extension=".md",
            file_name="CLAUDE.md",
            supports_xml=True,
            supports_mermaid=True,
            supports_file_refs=True,
            supports_yolo=True,
            max_context_tokens=200_000,
            handoff_method="file",
            cli_command="claude --file {file}",
            description="Anthropic's Claude Code CLI",
        )

    def format_context(
        self,
        task: str,
        plan: dict[str, Any],
        repo_map: str,
        memory: list[dict[str, str]],
        token_budget: int,
    ) -> str:
        """Format context as XML-structured CLAUDE.md.

        Args:
            task: Task description.
            plan: Structured plan dictionary.
            repo_map: Repository map string.
            memory: Relevant memory entries.
            token_budget: Maximum tokens for the output.

        Returns:
            XML-structured markdown handoff document.
        """
        sections: list[str] = []

        sections.append(f"# Task\n\n{task}")

        if plan:
            phases = plan.get("phases", [])
            if phases:
                sections.append("<plan>")
                for phase in phases:
                    if isinstance(phase, dict):
                        title = phase.get("title", "Untitled")
                        desc = phase.get("description", "")
                        sections.append(f"## {title}\n\n{desc}")
                        files = phase.get("files", [])
                        if files:
                            sections.append("### Files")
                            for f in files:
                                if isinstance(f, dict):
                                    sections.append(
                                        f"- `{f.get('path', '')}`: {f.get('description', '')}"
                                    )
                        criteria = phase.get("acceptance_criteria", [])
                        if criteria:
                            sections.append("### Acceptance Criteria")
                            for c in criteria:
                                sections.append(f"- [ ] {c}")
                sections.append("</plan>")

        if repo_map:
            sections.append(f"<repo_map>\n{repo_map}\n</repo_map>")

        if memory:
            sections.append("<memory>")
            for entry in memory:
                if isinstance(entry, dict):
                    summary = entry.get("summary", "")
                    rationale = entry.get("rationale", "")
                    sections.append(f"- **{summary}**: {rationale}")
            sections.append("</memory>")

        return "\n\n".join(sections)

    def format_verification_prompt(
        self,
        diff: str,
        plan: dict[str, Any],
    ) -> str:
        """Format verification prompt with XML structure for Claude.

        Args:
            diff: Git diff of changes to review.
            plan: The original plan dictionary.

        Returns:
            XML-structured verification prompt.
        """
        phases_text = ""
        for phase in plan.get("phases", []):
            if isinstance(phase, dict):
                title = phase.get("title", "Untitled")
                desc = phase.get("description", "")
                phases_text += f"- {title}: {desc}\n"
                criteria = phase.get("acceptance_criteria", [])
                for c in criteria:
                    phases_text += f"  - [ ] {c}\n"

        return f"""<verification>
<plan>
{phases_text or "No plan provided."}
</plan>

<diff>
{diff}
</diff>

<instructions>
Review the diff against the plan. For each phase:
1. Check that all acceptance criteria are met.
2. Identify any unintended side effects.
3. Flag missing error handling or test coverage.
4. Rate the change as: PASS, WARN, or FAIL.
</instructions>
</verification>"""
