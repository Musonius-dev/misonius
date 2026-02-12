"""L1: Intent Engine — captures and refines user intent through structured clarification."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from musonius.orchestration.router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class Question:
    """A clarifying question to ask the user.

    Attributes:
        id: Unique question identifier.
        category: Question category (business, architecture, constraints, edge_cases).
        question: The question text.
        why_asking: Explanation of why this question matters for planning.
    """

    id: str
    category: str
    question: str
    why_asking: str


@dataclass
class Intent:
    """Refined user intent ready for planning.

    Attributes:
        task_description: Original task description from the user.
        business_goals: Identified business goals and user impact.
        technical_constraints: Technical limitations and requirements.
        edge_cases: Error scenarios, boundary conditions, failure modes.
        success_criteria: Measurable criteria for task completion.
        clarification_history: List of (Question, answer) pairs from clarification.
        created_at: Timestamp when the intent was created.
    """

    task_description: str
    business_goals: list[str] = field(default_factory=list)
    technical_constraints: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    clarification_history: list[tuple[Question, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_refined(self) -> bool:
        """Whether the intent has been refined with clarifications."""
        return len(self.clarification_history) > 0

    @property
    def is_valid(self) -> bool:
        """Whether the intent has sufficient detail for planning.

        Validation rules:
        - Task description must be non-empty
        - At least one success criterion should be defined
        """
        return bool(self.task_description.strip()) and len(self.success_criteria) > 0

    def summary(self) -> str:
        """Generate a text summary of the refined intent for downstream consumption.

        Returns:
            Formatted summary string suitable for passing to the planning engine.
        """
        parts = [f"Task: {self.task_description}"]

        if self.business_goals:
            parts.append("\nBusiness Goals:")
            for goal in self.business_goals:
                parts.append(f"  - {goal}")

        if self.technical_constraints:
            parts.append("\nTechnical Constraints:")
            for constraint in self.technical_constraints:
                parts.append(f"  - {constraint}")

        if self.edge_cases:
            parts.append("\nEdge Cases:")
            for case in self.edge_cases:
                parts.append(f"  - {case}")

        if self.success_criteria:
            parts.append("\nSuccess Criteria:")
            for criterion in self.success_criteria:
                parts.append(f"  - {criterion}")

        if self.clarification_history:
            parts.append("\nClarifications:")
            for question, answer in self.clarification_history:
                parts.append(f"  Q: {question.question}")
                parts.append(f"  A: {answer}")

        return "\n".join(parts)


def make_question_id() -> str:
    """Generate a unique question identifier.

    Returns:
        Short UUID string for question identification.
    """
    return f"q-{uuid.uuid4().hex[:8]}"


class IntentEngine:
    """Captures and refines user intent through structured clarification.

    Uses the scout model (free tier) to generate targeted clarifying questions,
    then refines the intent based on user answers before handing off to planning.

    Args:
        router: Model router for scout model calls.
    """

    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    def capture_intent(
        self,
        task_description: str,
        auto_clarify: bool = True,
        context: dict[str, str] | None = None,
    ) -> Intent:
        """Capture user intent, optionally generating clarifying questions.

        When auto_clarify is True, generates questions via the scout model
        but does NOT collect answers — that's the CLI layer's responsibility.
        The returned Intent will have questions available but no answers yet.

        Args:
            task_description: User's natural language task description.
            auto_clarify: Whether to generate clarifying questions.
            context: Optional additional context (repo_map, conventions, etc.).

        Returns:
            Intent object. If auto_clarify is True, call ask_clarifying_questions
            separately to get the questions, then refine_intent with answers.
        """
        intent = Intent(task_description=task_description.strip())

        if auto_clarify:
            logger.info("Auto-clarification enabled, questions will be generated on demand")

        return intent

    def ask_clarifying_questions(
        self,
        task_description: str,
        context: dict[str, str] | None = None,
    ) -> list[Question]:
        """Generate 3-5 targeted clarifying questions via the scout model.

        Uses the scout model (free tier) to analyze the task and generate
        questions about business goals, architecture needs, constraints,
        and edge cases.

        Args:
            task_description: User's task description.
            context: Optional additional context (repo_map, conventions, etc.).

        Returns:
            List of 3-5 Question objects.
        """
        from musonius.intent.clarifier import generate_questions_via_scout

        return generate_questions_via_scout(
            router=self.router,
            task_description=task_description,
            context=context or {},
        )

    def refine_intent(
        self,
        original_intent: Intent,
        answers: dict[str, str],
        questions: list[Question],
    ) -> Intent:
        """Refine intent based on user answers to clarifying questions.

        Categorizes answers into business_goals, technical_constraints,
        edge_cases, and success_criteria based on the question categories.

        Args:
            original_intent: The initial Intent to refine.
            answers: Mapping of question ID to user answer text.
            questions: The questions that were asked.

        Returns:
            Refined Intent with populated fields.
        """
        question_map = {q.id: q for q in questions}

        business_goals: list[str] = list(original_intent.business_goals)
        technical_constraints: list[str] = list(original_intent.technical_constraints)
        edge_cases: list[str] = list(original_intent.edge_cases)
        success_criteria: list[str] = list(original_intent.success_criteria)
        history: list[tuple[Question, str]] = list(original_intent.clarification_history)

        for question_id, answer in answers.items():
            question = question_map.get(question_id)
            if not question or not answer.strip():
                continue

            history.append((question, answer.strip()))

            if question.category == "business":
                business_goals.append(answer.strip())
            elif question.category in ("architecture", "constraints"):
                technical_constraints.append(answer.strip())
            elif question.category == "edge_cases":
                edge_cases.append(answer.strip())

        # If no explicit success criteria yet, derive from business goals
        if not success_criteria and business_goals:
            success_criteria.append(f"Achieves: {business_goals[0]}")

        return Intent(
            task_description=original_intent.task_description,
            business_goals=business_goals,
            technical_constraints=technical_constraints,
            edge_cases=edge_cases,
            success_criteria=success_criteria,
            clarification_history=history,
            created_at=original_intent.created_at,
        )

    def validate_intent(self, intent: Intent) -> list[str]:
        """Validate that an intent has sufficient detail for planning.

        Checks:
        - Task description is non-empty
        - At least one success criterion defined
        - Technical constraints identified (warning only)

        Args:
            intent: Intent to validate.

        Returns:
            List of validation warning messages (empty if fully valid).
        """
        warnings: list[str] = []

        if not intent.task_description.strip():
            warnings.append("Task description is empty")

        if not intent.success_criteria:
            warnings.append("No success criteria defined")

        if not intent.technical_constraints:
            warnings.append("No technical constraints identified (may be fine for simple tasks)")

        if not intent.edge_cases:
            warnings.append("No edge cases considered (may be fine for simple tasks)")

        return warnings
