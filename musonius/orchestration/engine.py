"""L4: Orchestration Engine — coordinates model routing and agent handoff."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from musonius.context.agents.base import AgentPlugin
    from musonius.context.agents.registry import AgentRegistry
    from musonius.orchestration.router import ModelRouter

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    """Coordinates model routing and generates agent-specific handoff documents.

    Args:
        router: Model router for LLM calls.
        agent_registry: Registry of available agent plugins.
    """

    def __init__(self, router: ModelRouter, agent_registry: AgentRegistry) -> None:
        self.router = router
        self.agent_registry = agent_registry

    def get_agent(self, agent_name: str) -> AgentPlugin:
        """Get an agent plugin by name.

        Args:
            agent_name: Name of the agent (e.g., "claude", "gemini").

        Returns:
            The agent plugin instance.

        Raises:
            KeyError: If the agent is not registered.
        """
        return self.agent_registry.get(agent_name)

    def generate_handoff(
        self,
        agent_name: str,
        task: str,
        plan: dict[str, Any],
        repo_map: str,
        memory: list[dict[str, str]],
        token_budget: int,
        output_path: Path | None = None,
    ) -> str:
        """Generate an agent-specific handoff document.

        Args:
            agent_name: Target agent name.
            task: Task description.
            plan: Plan dictionary.
            repo_map: Repo map string.
            memory: Memory entries.
            token_budget: Token budget for the handoff.
            output_path: Optional path to write the handoff file.

        Returns:
            Formatted handoff document string.
        """
        agent = self.get_agent(agent_name)
        handoff = agent.format_context(
            task=task,
            plan=plan,
            repo_map=repo_map,
            memory=memory,
            token_budget=token_budget,
        )

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(handoff)
            logger.info("Handoff written to %s", output_path)

        return handoff
