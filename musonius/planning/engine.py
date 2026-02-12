"""L3: Planning Engine — generates phased implementation plans from user intent."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from musonius.memory.store import MemoryStore
from musonius.orchestration.router import ModelRouter
from musonius.planning.prompts import build_plan_prompt
from musonius.planning.schemas import FileChange, Phase, Plan

logger = logging.getLogger(__name__)

# Token estimation constants per file action
_CREATE_BASE_TOKENS = 500
_CREATE_PER_CHANGE_TOKENS = 300
_MODIFY_BASE_TOKENS = 200
_MODIFY_PER_CHANGE_TOKENS = 200
_DELETE_TOKENS = 50
_ESTIMATION_BUFFER = 1.2  # 20% buffer


class PlanningEngine:
    """Generates and manages phased implementation plans.

    Args:
        memory: Memory store for decisions and conventions.
        router: Model router for LLM calls.
        project_root: Project root directory.
    """

    def __init__(
        self,
        memory: MemoryStore,
        router: ModelRouter,
        project_root: Path,
    ) -> None:
        self.memory = memory
        self.router = router
        self.project_root = project_root

    def generate_plan(
        self,
        task_description: str,
        max_phases: int = 1,
        repo_map: str = "",
    ) -> Plan:
        """Generate an implementation plan for a task.

        Args:
            task_description: Description of what to implement.
            max_phases: Maximum number of phases in the plan.
            repo_map: Optional repo map context.

        Returns:
            Structured Plan object.
        """
        # Gather context from memory
        decisions = self.memory.search_decisions(task_description)
        conventions = self.memory.get_all_conventions()
        failures = self.memory.search_failures(task_description)

        decisions_text = "\n".join(
            f"- {d.get('summary', '')}: {d.get('rationale', '')}" for d in decisions
        )
        conventions_text = "\n".join(
            f"- [{c.get('pattern', '')}] {c.get('rule', '')}" for c in conventions
        )
        failures_text = "\n".join(
            f"- FAILED: {f.get('approach', '')} — {f.get('failure_reason', '')}"
            for f in failures
        )

        messages = build_plan_prompt(
            task_description=task_description,
            repo_map=repo_map,
            decisions=decisions_text,
            conventions=conventions_text,
            failures=failures_text,
            max_phases=max_phases,
        )

        response = self.router.call_planner(messages)

        plan = self._parse_plan_response(response.content, task_description)
        self._save_plan(plan)

        return plan

    def _parse_plan_response(self, response_text: str, task_description: str) -> Plan:
        """Parse the LLM response into a Plan object.

        Args:
            response_text: Raw LLM response text.
            task_description: Original task description.

        Returns:
            Parsed Plan object.
        """
        epic_id = f"epic-{uuid.uuid4().hex[:8]}"

        # Extract JSON from the response
        plan_data = self._extract_json(response_text)

        phases: list[Phase] = []
        for phase_data in plan_data.get("phases", []):
            files = [
                FileChange(
                    path=f.get("path", ""),
                    action=f.get("action", "modify"),
                    description=f.get("description", ""),
                    key_changes=f.get("key_changes", []),
                )
                for f in phase_data.get("files", [])
            ]

            phase = Phase(
                id=phase_data.get("id", f"phase-{len(phases) + 1}"),
                title=phase_data.get("title", "Untitled Phase"),
                description=phase_data.get("description", ""),
                files=files,
                dependencies=phase_data.get("dependencies", []),
                acceptance_criteria=phase_data.get("acceptance_criteria", []),
                test_strategy=phase_data.get("test_strategy", ""),
                estimated_tokens=estimate_phase_tokens(files),
            )
            phases.append(phase)

        total_tokens = sum(p.estimated_tokens for p in phases)

        return Plan(
            epic_id=epic_id,
            task_description=task_description,
            phases=phases,
            total_estimated_tokens=total_tokens,
        )

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from LLM response, handling markdown code blocks.

        Args:
            text: Raw response text.

        Returns:
            Parsed JSON dictionary.
        """
        # Try direct parse first
        try:
            parsed: dict[str, Any] = json.loads(text)
            return parsed
        except json.JSONDecodeError:
            pass

        # Try extracting from code block
        if "```" in text:
            blocks = text.split("```")
            for block in blocks:
                clean = block.strip()
                if clean.startswith("json"):
                    clean = clean[4:].strip()
                try:
                    parsed = json.loads(clean)
                    return parsed
                except json.JSONDecodeError:
                    continue

        logger.warning("Failed to parse plan JSON, returning empty plan")
        return {"phases": []}

    def _save_plan(self, plan: Plan) -> None:
        """Save a plan to the .musonius/epics/ directory.

        Args:
            plan: Plan to save.
        """
        epics_dir = self.project_root / ".musonius" / "epics" / plan.epic_id
        phases_dir = epics_dir / "phases"
        phases_dir.mkdir(parents=True, exist_ok=True)

        # Save spec
        spec_path = epics_dir / "spec.md"
        spec_content = f"# {plan.task_description}\n\n"
        spec_content += f"Epic ID: {plan.epic_id}\n"
        spec_content += f"Created: {plan.created_at.isoformat()}\n"
        spec_content += f"Phases: {len(plan.phases)}\n"
        spec_content += f"Estimated tokens: {plan.total_estimated_tokens}\n"
        spec_path.write_text(spec_content)

        # Save each phase
        for i, phase in enumerate(plan.phases, 1):
            phase_path = phases_dir / f"phase-{i:02d}.md"
            content = f"# {phase.title}\n\n"
            content += f"{phase.description}\n\n"

            if phase.dependencies:
                content += "## Dependencies\n\n"
                for dep in phase.dependencies:
                    content += f"- {dep}\n"
                content += "\n"

            if phase.files:
                content += "## Files\n\n"
                for fc in phase.files:
                    content += f"- **{fc.action}** `{fc.path}`: {fc.description}\n"
                    for change in fc.key_changes:
                        content += f"  - {change}\n"
                content += "\n"

            if phase.acceptance_criteria:
                content += "## Acceptance Criteria\n\n"
                for criterion in phase.acceptance_criteria:
                    content += f"- [ ] {criterion}\n"
                content += "\n"

            if phase.test_strategy:
                content += f"## Test Strategy\n\n{phase.test_strategy}\n\n"

            content += f"## Estimates\n\nEstimated tokens: {phase.estimated_tokens}\n"

            phase_path.write_text(content)

        logger.info("Saved plan %s with %d phases to %s", plan.epic_id, len(plan.phases), epics_dir)

    def validate_plan(self, plan: Plan) -> list[str]:
        """Validate a plan for completeness and correctness.

        Args:
            plan: Plan to validate.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors: list[str] = []

        if not plan.phases:
            errors.append("Plan has no phases")
            return errors

        phase_ids = {p.id for p in plan.phases}

        for phase in plan.phases:
            if not phase.files:
                errors.append(f"Phase '{phase.title}' has no files")
            if not phase.acceptance_criteria:
                errors.append(f"Phase '{phase.title}' has no acceptance criteria")
            if not phase.test_strategy:
                errors.append(f"Phase '{phase.title}' has no test strategy")

            # Validate dependencies reference existing phases
            for dep in phase.dependencies:
                if dep not in phase_ids:
                    errors.append(
                        f"Phase '{phase.title}' has invalid dependency '{dep}'"
                    )

            for fc in phase.files:
                if fc.action not in ("create", "modify", "delete"):
                    errors.append(f"Invalid action '{fc.action}' for file {fc.path}")
                if fc.action == "modify":
                    full_path = self.project_root / fc.path
                    if not full_path.exists():
                        errors.append(
                            f"File '{fc.path}' marked for modify but does not exist"
                        )

        # Check for dependency cycles
        cycle_error = _detect_dependency_cycle(plan.phases)
        if cycle_error:
            errors.append(cycle_error)

        return errors


def estimate_phase_tokens(files: list[FileChange]) -> int:
    """Estimate tokens needed to implement a phase.

    Heuristic:
        - Create file: 500 base + 300 per key change
        - Modify file: 200 base + 200 per key change
        - Delete file: 50 flat
        - All estimates get a 20% buffer

    Args:
        files: List of file changes in the phase.

    Returns:
        Estimated token count.
    """
    total = 0
    for fc in files:
        if fc.action == "create":
            total += _CREATE_BASE_TOKENS + _CREATE_PER_CHANGE_TOKENS * len(fc.key_changes)
        elif fc.action == "modify":
            total += _MODIFY_BASE_TOKENS + _MODIFY_PER_CHANGE_TOKENS * len(fc.key_changes)
        else:  # delete
            total += _DELETE_TOKENS

    return int(total * _ESTIMATION_BUFFER)


def _detect_dependency_cycle(phases: list[Phase]) -> str | None:
    """Detect cycles in phase dependencies using DFS.

    Args:
        phases: List of phases to check.

    Returns:
        Error message if a cycle is found, None otherwise.
    """
    adjacency: dict[str, list[str]] = {p.id: list(p.dependencies) for p in phases}
    visited: set[str] = set()
    in_stack: set[str] = set()

    def _dfs(node: str) -> bool:
        visited.add(node)
        in_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                if _dfs(neighbor):
                    return True
            elif neighbor in in_stack:
                return True
        in_stack.discard(node)
        return False

    for phase_id in adjacency:
        if phase_id not in visited and _dfs(phase_id):
            return "Plan has circular phase dependencies"

    return None
