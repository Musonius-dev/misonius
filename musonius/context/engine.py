"""L2: Context Engine — assembles token-budgeted context for downstream agents."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from musonius.context.budget import (
    BudgetAllocation,
    allocate_budget,
    count_tokens,
    truncate_to_budget,
)

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    """Assembled context for a task.

    Attributes:
        formatted_output: The final formatted handoff string (agent-specific).
        repo_map: Raw repo map string.
        relevant_files: List of prioritized file paths.
        memory_decisions: Matching architectural decisions.
        memory_conventions: Coding conventions.
        memory_failures: Known failed approaches.
        budget_allocation: Token budget breakdown.
        token_count: Actual tokens used in the formatted output.
        detail_level: Repo map detail level used.
    """

    formatted_output: str = ""
    repo_map: str = ""
    relevant_files: list[Path] = field(default_factory=list)
    memory_decisions: list[dict[str, Any]] = field(default_factory=list)
    memory_conventions: list[dict[str, Any]] = field(default_factory=list)
    memory_failures: list[dict[str, Any]] = field(default_factory=list)
    budget_allocation: BudgetAllocation | None = None
    token_count: int = 0
    detail_level: int = 1


class ContextEngine:
    """Assembles optimized, token-budgeted context from index, memory, and repo map.

    The Context Engine is the core orchestrator of Layer 2. It pre-computes
    codebase structure via tree-sitter, queries persistent memory, and
    generates agent-specific handoff documents within token budgets.

    Args:
        project_root: Root directory of the target project.
        indexer: Tree-sitter codebase indexer.
        repo_map_generator: Multi-level repo map generator.
        memory_store: Persistent memory store.
    """

    def __init__(
        self,
        project_root: Path,
        indexer: object,
        repo_map_generator: object,
        memory_store: object,
    ) -> None:
        self.project_root = project_root
        self.indexer = indexer
        self.repo_map_generator = repo_map_generator
        self.memory_store = memory_store

    def get_context(
        self,
        task: str,
        plan: dict[str, Any] | None = None,
        agent: str = "claude",
        token_budget: int | None = None,
    ) -> ContextResult:
        """Assemble token-budgeted context for a task and agent.

        This is the primary entry point. It:
        1. Resolves the token budget from the agent's capabilities
        2. Allocates budget across components (task/plan/memory/repo)
        3. Queries memory for relevant decisions, conventions, failures
        4. Extracts relevant files from the plan
        5. Generates a repo map at the auto-selected detail level
        6. Formats everything via the agent's plugin

        Args:
            task: Task description.
            plan: Plan dictionary with phases and file references.
            agent: Agent slug (e.g., "claude", "gemini", "generic").
            token_budget: Max tokens. Auto-detected from agent if None.

        Returns:
            ContextResult with the formatted handoff and metadata.
        """
        if plan is None:
            plan = {}

        from musonius.context.agents.registry import create_default_registry

        registry = create_default_registry()
        plugin = registry.get(agent)
        caps = plugin.capabilities()

        # Resolve token budget
        effective_budget = token_budget if token_budget is not None else caps.max_context_tokens

        # Allocate budget across components
        allocation = allocate_budget(effective_budget)

        # Query memory
        decisions = self._query_decisions(task)
        conventions = self._query_conventions()
        failures = self._query_failures(task)

        # Extract relevant files from plan
        relevant_files = self._extract_plan_files(plan)

        # Generate repo map at the auto-selected detail level
        repo_map = self._generate_repo_map(
            relevant_files=relevant_files,
            token_budget=allocation.repo,
            detail_level=allocation.detail_level,
        )

        # Build memory entries for the agent plugin
        memory_entries = self._build_memory_entries(
            decisions, conventions, failures, allocation.memory
        )

        # Truncate plan content to budget
        plan_text = self._format_plan_for_budget(plan, allocation.plan)

        # Format via agent plugin
        formatted = plugin.format_context(
            task=task,
            plan=plan_text if isinstance(plan_text, dict) else plan,
            repo_map=repo_map,
            memory=memory_entries,
            token_budget=effective_budget,
        )

        actual_tokens = count_tokens(formatted)

        return ContextResult(
            formatted_output=formatted,
            repo_map=repo_map,
            relevant_files=relevant_files,
            memory_decisions=decisions,
            memory_conventions=conventions,
            memory_failures=failures,
            budget_allocation=allocation,
            token_count=actual_tokens,
            detail_level=allocation.detail_level,
        )

    def gather_context(
        self,
        task_description: str,
        relevant_files: list[Path] | None = None,
        token_budget: int = 8000,
        detail_level: int = 1,
    ) -> ContextResult:
        """Gather token-budgeted context for a task (low-level API).

        This is the simpler interface that returns raw context without
        agent-specific formatting. Use get_context() for full pipeline.

        Args:
            task_description: Description of the task.
            relevant_files: Specific files to prioritize, or None for auto-detection.
            token_budget: Maximum tokens for the context.
            detail_level: Repo map detail level (0-3).

        Returns:
            Assembled context result.
        """
        if relevant_files is None:
            relevant_files = []

        decisions = self._query_decisions(task_description)
        conventions = self._query_conventions()
        failures = self._query_failures(task_description)

        allocation = allocate_budget(token_budget)

        repo_map = self._generate_repo_map(
            relevant_files=relevant_files,
            token_budget=allocation.repo,
            detail_level=detail_level,
        )

        return ContextResult(
            repo_map=repo_map,
            relevant_files=relevant_files,
            memory_decisions=decisions,
            memory_conventions=conventions,
            memory_failures=failures,
            budget_allocation=allocation,
            token_count=count_tokens(repo_map),
            detail_level=detail_level,
        )

    def _query_decisions(self, task: str) -> list[dict[str, Any]]:
        """Query memory for relevant architectural decisions.

        Args:
            task: Task description for keyword search.

        Returns:
            List of matching decision dicts.
        """
        try:
            return self.memory_store.search_decisions(task)  # type: ignore[union-attr]
        except Exception as e:
            logger.debug("Failed to query decisions: %s", e)
            return []

    def _query_conventions(self) -> list[dict[str, Any]]:
        """Get all coding conventions from memory.

        Returns:
            List of convention dicts.
        """
        try:
            return self.memory_store.get_all_conventions()  # type: ignore[union-attr]
        except Exception as e:
            logger.debug("Failed to query conventions: %s", e)
            return []

    def _query_failures(self, task: str) -> list[dict[str, Any]]:
        """Query memory for past failed approaches.

        Args:
            task: Task description for keyword search.

        Returns:
            List of matching failure dicts.
        """
        try:
            return self.memory_store.search_failures(task)  # type: ignore[union-attr]
        except Exception as e:
            logger.debug("Failed to query failures: %s", e)
            return []

    def _extract_plan_files(self, plan: dict[str, Any]) -> list[Path]:
        """Extract file paths referenced in a plan.

        Walks through plan phases and collects file paths mentioned
        in 'files' entries or extracted from descriptions.

        Args:
            plan: Plan dictionary with phases.

        Returns:
            Deduplicated list of file paths.
        """
        seen: set[str] = set()
        result: list[Path] = []

        for phase in plan.get("phases", []):
            if not isinstance(phase, dict):
                continue

            # Extract from structured file entries
            for file_entry in phase.get("files", []):
                path_str = ""
                if isinstance(file_entry, dict):
                    path_str = file_entry.get("path", "")
                elif isinstance(file_entry, str):
                    path_str = file_entry

                if path_str and path_str not in seen:
                    seen.add(path_str)
                    result.append(Path(path_str))

            # Extract file paths from description text
            description = phase.get("description", "")
            if description:
                for match in re.findall(r'`([^`]+\.py)`', description):
                    if match not in seen:
                        seen.add(match)
                        result.append(Path(match))

        return result

    def _generate_repo_map(
        self,
        relevant_files: list[Path],
        token_budget: int,
        detail_level: int,
    ) -> str:
        """Generate a repo map at the specified detail level.

        Args:
            relevant_files: Files to prioritize.
            token_budget: Token budget for the map.
            detail_level: Detail level (0-3).

        Returns:
            Repo map string, or empty string on error.
        """
        try:
            return self.repo_map_generator.generate(  # type: ignore[union-attr]
                level=detail_level,
                relevant_files=relevant_files,
                token_budget=token_budget,
            )
        except Exception as e:
            logger.warning("Failed to generate repo map: %s", e)
            return ""

    def _build_memory_entries(
        self,
        decisions: list[dict[str, Any]],
        conventions: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        memory_budget: int,
    ) -> list[dict[str, str]]:
        """Build a unified list of memory entries for agent formatting.

        Combines decisions, conventions, and failures into a flat list
        of dicts with 'summary' and 'rationale' keys. Truncates to fit
        the memory token budget.

        Args:
            decisions: Architectural decisions.
            conventions: Coding conventions.
            failures: Failed approaches.
            memory_budget: Maximum tokens for memory section.

        Returns:
            List of memory entry dicts within budget.
        """
        entries: list[dict[str, str]] = []

        for d in decisions:
            entries.append({
                "summary": d.get("summary", ""),
                "rationale": d.get("rationale", ""),
                "category": d.get("category", "decision"),
            })

        for c in conventions:
            entries.append({
                "summary": f"[{c.get('pattern', '')}] {c.get('rule', '')}",
                "rationale": f"Source: {c.get('source', 'unknown')}",
                "category": "convention",
            })

        for f in failures:
            approach = f.get("approach", "")
            reason = f.get("failure_reason", "")
            alt = f.get("alternative", "")
            entries.append({
                "summary": f"AVOID: {approach}",
                "rationale": f"Failed because: {reason}"
                + (f" — Use instead: {alt}" if alt else ""),
                "category": "failure",
            })

        # Truncate entries to fit memory budget
        result: list[dict[str, str]] = []
        running_tokens = 0

        for entry in entries:
            entry_text = f"{entry['summary']}: {entry['rationale']}"
            entry_tokens = count_tokens(entry_text)
            if running_tokens + entry_tokens > memory_budget:
                break
            result.append(entry)
            running_tokens += entry_tokens

        return result

    def _format_plan_for_budget(
        self, plan: dict[str, Any], plan_budget: int
    ) -> dict[str, Any]:
        """Truncate plan content to fit within the plan token budget.

        Args:
            plan: Full plan dictionary.
            plan_budget: Maximum tokens for the plan section.

        Returns:
            Plan dictionary with descriptions truncated if needed.
        """
        if not plan or not plan.get("phases"):
            return plan

        import json

        plan_json = json.dumps(plan)
        plan_tokens = count_tokens(plan_json)

        if plan_tokens <= plan_budget:
            return plan

        # Truncate phase descriptions to fit
        truncated_plan = dict(plan)
        truncated_phases: list[dict[str, Any]] = []
        remaining = plan_budget

        for phase in plan.get("phases", []):
            if not isinstance(phase, dict):
                continue
            phase_copy = dict(phase)
            desc = phase_copy.get("description", "")
            if desc and count_tokens(desc) > remaining // max(1, len(plan.get("phases", []))):
                per_phase = remaining // max(1, len(plan.get("phases", [])))
                phase_copy["description"] = truncate_to_budget(desc, max(50, per_phase))
            truncated_phases.append(phase_copy)

        truncated_plan["phases"] = truncated_phases
        return truncated_plan
