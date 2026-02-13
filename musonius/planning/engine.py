"""L3: Planning Engine — generates phased implementation plans from user intent."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Callable

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
        on_status: Callable[[str], None] | None = None,
    ) -> Plan:
        """Generate an implementation plan for a task.

        Args:
            task_description: Description of what to implement.
            max_phases: Maximum number of phases in the plan.
            repo_map: Optional repo map context.
            on_status: Optional callback for progress updates.

        Returns:
            Structured Plan object.
        """
        def _status(msg: str) -> None:
            if on_status:
                on_status(msg)

        # Gather context from memory
        _status("Querying project memory...")
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

        _status("Building plan prompt...")
        messages = build_plan_prompt(
            task_description=task_description,
            repo_map=repo_map,
            decisions=decisions_text,
            conventions=conventions_text,
            failures=failures_text,
            max_phases=max_phases,
        )

        _status("Calling LLM for plan generation...")
        response = self.router.call_planner(messages, on_status=on_status)

        _status("Parsing plan response...")
        raw_data = self._extract_json(response.content)
        plan = self._parse_plan_response(response.content, task_description)

        # Validate plan and log warnings
        _status("Validating plan...")
        validation_errors = self.validate_plan(plan)
        for error in validation_errors:
            logger.warning("Plan validation: %s", error)

        # Extract and store architectural decisions from plan output
        _status("Storing architectural decisions...")
        self._extract_and_store_decisions(raw_data, plan.epic_id)

        # Generate SOT files from decisions
        self._generate_sot_files(raw_data, plan.epic_id)

        _status("Saving plan to disk...")
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
        """Extract JSON from LLM response, handling various response formats.

        Handles:
        - Pure JSON responses
        - JSON wrapped in markdown code blocks (```json ... ```)
        - JSON embedded in conversational text (Claude CLI often does this)
        - Brace-matched extraction as last resort

        Args:
            text: Raw response text.

        Returns:
            Parsed JSON dictionary.
        """
        # Strategy 1: Try direct parse
        try:
            parsed: dict[str, Any] = json.loads(text.strip())
            return parsed
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract from markdown code blocks
        if "```" in text:
            blocks = text.split("```")
            for block in blocks:
                clean = block.strip()
                for prefix in ("json", "JSON", "javascript", "js"):
                    if clean.startswith(prefix):
                        clean = clean[len(prefix):].strip()
                        break
                try:
                    parsed = json.loads(clean)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    continue

        # Strategy 3: Brace-matched extraction — find JSON objects in text
        candidates: list[str] = []
        depth = 0
        start = -1
        for i, char in enumerate(text):
            if char == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    candidates.append(text[start : i + 1])
                    start = -1

        # Try candidates from largest to smallest
        candidates.sort(key=len, reverse=True)
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and (
                    "phases" in parsed or "architecture_decisions" in parsed
                ):
                    return parsed
            except json.JSONDecodeError:
                continue

        # Try any valid dict candidate
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        logger.warning("Failed to parse plan JSON from response (%d chars)", len(text))
        logger.debug("Response preview: %.500s", text[:500])
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

    def _extract_and_store_decisions(
        self, raw_data: dict[str, Any], epic_id: str
    ) -> int:
        """Extract architectural decisions from plan output and store in memory.

        Args:
            raw_data: Raw parsed JSON from LLM response.
            epic_id: Epic ID to associate decisions with.

        Returns:
            Number of decisions stored.
        """
        decisions = raw_data.get("architecture_decisions", [])
        stored = 0

        for decision in decisions:
            if not isinstance(decision, dict):
                continue

            summary = decision.get("summary", "")
            if not summary:
                continue

            try:
                self.memory.add_decision(
                    summary=summary,
                    rationale=decision.get("rationale", ""),
                    category=decision.get("category", "architecture"),
                    epic_id=epic_id,
                    files_affected=decision.get("files_affected"),
                    confidence=0.85,
                )
                stored += 1
            except Exception as e:
                logger.debug("Failed to store decision '%s': %s", summary, e)

        if stored:
            logger.info("Stored %d architectural decisions from plan %s", stored, epic_id)

        return stored

    def _generate_sot_files(
        self, raw_data: dict[str, Any], epic_id: str
    ) -> list[Path]:
        """Generate Source of Truth files from architectural decisions.

        Creates versioned markdown files in .musonius/sot/ like TECH-001.md,
        API-001.md, etc. based on decision categories.

        Args:
            raw_data: Raw parsed JSON from LLM response.
            epic_id: Epic ID for traceability.

        Returns:
            List of paths to created SOT files.
        """
        decisions = raw_data.get("architecture_decisions", [])
        if not decisions:
            return []

        sot_dir = self.project_root / ".musonius" / "sot"
        sot_dir.mkdir(parents=True, exist_ok=True)

        # Category to SOT prefix mapping
        category_prefix = {
            "architecture": "ARCH",
            "dependency": "DEP",
            "pattern": "CONV",
            "api": "API",
            "security": "SEC",
            "performance": "PERF",
            "general": "TECH",
        }

        created_files: list[Path] = []

        for decision in decisions:
            if not isinstance(decision, dict) or not decision.get("summary"):
                continue

            category = decision.get("category", "general")
            prefix = category_prefix.get(category, "TECH")

            # Find next available ID for this prefix
            existing = sorted(sot_dir.glob(f"{prefix}-*.md"))
            if existing:
                last_num = 0
                for f in existing:
                    try:
                        num = int(f.stem.split("-")[1])
                        last_num = max(last_num, num)
                    except (IndexError, ValueError):
                        pass
                next_num = last_num + 1
            else:
                next_num = 1

            sot_id = f"{prefix}-{next_num:03d}"
            sot_path = sot_dir / f"{sot_id}.md"

            # Build SOT content
            content = f"# {sot_id}: {decision.get('summary', 'Untitled')}\n\n"
            content += f"**Category:** {category}\n"
            content += f"**Epic:** {epic_id}\n"
            content += f"**Status:** Active\n\n"

            if decision.get("rationale"):
                content += f"## Rationale\n\n{decision['rationale']}\n\n"

            if decision.get("files_affected"):
                content += "## Files Affected\n\n"
                for f_path in decision["files_affected"]:
                    content += f"- `{f_path}`\n"
                content += "\n"

            content += "## History\n\n"
            content += f"- Created during planning of {epic_id}\n"

            sot_path.write_text(content)
            created_files.append(sot_path)
            logger.info("Created SOT file: %s", sot_id)

        return created_files

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
