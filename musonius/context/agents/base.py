"""Base class for agent plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AgentCapabilities:
    """Describes the capabilities of an agent plugin.

    Attributes:
        name: Human-readable agent name.
        slug: Short identifier (e.g., "claude", "gemini").
        file_extension: File extension for handoff documents.
        file_name: Default output filename (e.g., "CLAUDE.md").
        supports_xml: Whether the agent handles XML-structured prompts well.
        supports_mermaid: Whether the agent renders Mermaid diagrams.
        supports_file_refs: Whether the agent can open files by path.
        supports_yolo: Whether the agent can run autonomously.
        max_context_tokens: Maximum context window size.
        handoff_method: How to deliver the handoff ("file", "stdin", "clipboard", "cli_arg").
        cli_command: Optional CLI command template to invoke the agent.
        description: Short description of the agent.
    """

    name: str
    slug: str
    file_extension: str
    file_name: str
    supports_xml: bool
    supports_mermaid: bool
    supports_file_refs: bool
    supports_yolo: bool
    max_context_tokens: int
    handoff_method: str
    cli_command: str | None = None
    description: str = ""


class AgentPlugin(ABC):
    """Abstract base class for agent format plugins.

    Each plugin knows how to format context optimally for a specific
    AI coding agent (Claude Code, Gemini CLI, Cursor, etc.).
    """

    @abstractmethod
    def capabilities(self) -> AgentCapabilities:
        """Return the agent's capabilities descriptor.

        Returns:
            AgentCapabilities for this agent.
        """
        ...

    @abstractmethod
    def format_context(
        self,
        task: str,
        plan: dict[str, Any],
        repo_map: str,
        memory: list[dict[str, str]],
        token_budget: int,
    ) -> str:
        """Format context into an agent-specific handoff document.

        Args:
            task: Task description.
            plan: Structured plan dictionary.
            repo_map: Repository map string.
            memory: Relevant memory entries.
            token_budget: Maximum tokens for the output.

        Returns:
            Formatted handoff document string.
        """
        ...

    def format_verification_prompt(
        self,
        diff: str,
        plan: dict[str, Any],
    ) -> str:
        """Format a verification prompt for reviewing changes against the plan.

        Default implementation produces a generic markdown prompt. Plugins
        can override for agent-specific verification formatting.

        Args:
            diff: Git diff of changes to review.
            plan: The original plan dictionary.

        Returns:
            Formatted verification prompt string.
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

        return f"""# Verification Review

## Plan

{phases_text or "No plan provided."}

## Changes (Diff)

```diff
{diff}
```

## Instructions

Review the diff against the plan. For each phase:
1. Check that all acceptance criteria are met.
2. Identify any unintended side effects.
3. Flag missing error handling or test coverage.
4. Rate the change as: PASS, WARN, or FAIL.
"""

    def handoff_command(self, context_file: Path) -> str | None:
        """Return CLI command to invoke the agent with the context file.

        Returns None if manual handoff is required (no CLI command available).

        Args:
            context_file: Path to the generated context/handoff file.

        Returns:
            CLI command string, or None if manual handoff required.
        """
        caps = self.capabilities()
        if caps.cli_command:
            return caps.cli_command.replace("{file}", str(context_file))
        return None
