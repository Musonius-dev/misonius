"""Token budget management — counting and allocation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger(__name__)


# Budget allocation fractions per spec
TASK_FRACTION = 0.10
PLAN_FRACTION = 0.15
MEMORY_FRACTION = 0.05
REPO_FRACTION = 0.70

_ENCODER: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Get or create the tiktoken encoder (cached)."""
    global _ENCODER  # noqa: PLW0603
    if _ENCODER is None:
        try:
            _ENCODER = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            _ENCODER = tiktoken.get_encoding("cl100k_base")
    return _ENCODER


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string.

    Args:
        text: Text to count tokens for.

    Returns:
        Approximate token count.
    """
    encoder = _get_encoder()
    return len(encoder.encode(text))


def fits_budget(text: str, budget: int) -> bool:
    """Check if text fits within a token budget.

    Args:
        text: Text to check.
        budget: Maximum tokens allowed.

    Returns:
        True if text fits within budget.
    """
    return count_tokens(text) <= budget


def truncate_to_budget(text: str, budget: int) -> str:
    """Truncate text to fit within a token budget.

    Args:
        text: Text to truncate.
        budget: Maximum tokens allowed.

    Returns:
        Truncated text that fits within budget.
    """
    encoder = _get_encoder()
    tokens = encoder.encode(text)
    if len(tokens) <= budget:
        return text
    truncated_tokens = tokens[:budget]
    return encoder.decode(truncated_tokens)


@dataclass
class BudgetAllocation:
    """Token budget allocation across context components.

    Attributes:
        task: Tokens allocated for the task description.
        plan: Tokens allocated for the plan.
        memory: Tokens allocated for memory entries.
        repo: Tokens allocated for the repo map.
        detail_level: Recommended repo map detail level (0-3).
    """

    task: int
    plan: int
    memory: int
    repo: int
    detail_level: int


def allocate_budget(total_budget: int) -> BudgetAllocation:
    """Allocate tokens across context components with auto detail level.

    Applies the spec-defined allocation: 10% task, 15% plan, 5% memory,
    70% repo context. Selects the highest detail level that fits the repo
    budget.

    Args:
        total_budget: Total token budget available.

    Returns:
        BudgetAllocation with per-component budgets and detail level.
    """
    task_budget = int(total_budget * TASK_FRACTION)
    plan_budget = int(total_budget * PLAN_FRACTION)
    memory_budget = int(total_budget * MEMORY_FRACTION)
    repo_budget = int(total_budget * REPO_FRACTION)

    if repo_budget < 5_000:
        level = 0  # Skeleton
    elif repo_budget < 15_000:
        level = 1  # Signatures
    elif repo_budget < 30_000:
        level = 2  # Documented
    else:
        level = 3  # Full (for relevant files only)

    return BudgetAllocation(
        task=task_budget,
        plan=plan_budget,
        memory=memory_budget,
        repo=repo_budget,
        detail_level=level,
    )


class TokenBudgetManager:
    """Manages token budget allocation across context components.

    Args:
        total_budget: Total token budget available.
    """

    def __init__(self, total_budget: int) -> None:
        self.total_budget = total_budget
        self._allocations: dict[str, int] = {}
        self._used: dict[str, int] = {}

    def allocate(self, name: str, fraction: float) -> int:
        """Allocate a fraction of the total budget to a component.

        Args:
            name: Component name (e.g., "repo_map", "memory").
            fraction: Fraction of total budget (0.0-1.0).

        Returns:
            Number of tokens allocated.
        """
        allocation = int(self.total_budget * fraction)
        self._allocations[name] = allocation
        return allocation

    def record_usage(self, name: str, tokens: int) -> None:
        """Record actual token usage for a component.

        Args:
            name: Component name.
            tokens: Tokens actually used.
        """
        self._used[name] = tokens

    def remaining(self, name: str) -> int:
        """Get remaining budget for a component.

        Args:
            name: Component name.

        Returns:
            Remaining tokens available.
        """
        allocated = self._allocations.get(name, 0)
        used = self._used.get(name, 0)
        return max(0, allocated - used)

    @property
    def total_used(self) -> int:
        """Total tokens used across all components."""
        return sum(self._used.values())

    @property
    def total_remaining(self) -> int:
        """Total remaining tokens."""
        return max(0, self.total_budget - self.total_used)
