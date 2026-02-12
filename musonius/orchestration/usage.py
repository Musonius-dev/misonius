"""Usage tracker — records token consumption and cost across model calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """A single model usage record."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: float


class UsageTracker:
    """Tracks cumulative token usage and costs across model calls."""

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float = 0.0,
    ) -> None:
        """Record a model call's usage.

        Args:
            model: Model identifier.
            prompt_tokens: Number of prompt tokens.
            completion_tokens: Number of completion tokens.
            cost: Estimated cost in USD.
        """
        self._records.append(
            UsageRecord(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
            )
        )

    @property
    def total_tokens(self) -> int:
        """Total tokens across all calls."""
        return sum(r.prompt_tokens + r.completion_tokens for r in self._records)

    @property
    def total_prompt_tokens(self) -> int:
        """Total prompt tokens."""
        return sum(r.prompt_tokens for r in self._records)

    @property
    def total_completion_tokens(self) -> int:
        """Total completion tokens."""
        return sum(r.completion_tokens for r in self._records)

    @property
    def total_cost(self) -> float:
        """Total estimated cost in USD."""
        return sum(r.cost for r in self._records)

    @property
    def call_count(self) -> int:
        """Total number of model calls."""
        return len(self._records)

    def by_model(self) -> dict[str, dict[str, int | float]]:
        """Get usage breakdown by model.

        Returns:
            Dict mapping model name to usage stats.
        """
        breakdown: dict[str, dict[str, int | float]] = {}

        for r in self._records:
            if r.model not in breakdown:
                breakdown[r.model] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost": 0.0,
                    "calls": 0,
                }
            entry = breakdown[r.model]
            entry["prompt_tokens"] += r.prompt_tokens  # type: ignore[operator]
            entry["completion_tokens"] += r.completion_tokens  # type: ignore[operator]
            entry["total_tokens"] += r.prompt_tokens + r.completion_tokens  # type: ignore[operator]
            entry["cost"] += r.cost  # type: ignore[operator]
            entry["calls"] += 1  # type: ignore[operator]

        return breakdown

    def report(self) -> str:
        """Generate a formatted usage report string.

        Returns:
            Human-readable usage report with per-model breakdown and totals.
        """
        if not self._records:
            return "No model calls recorded."

        lines: list[str] = ["Token Usage Report", "=" * 50]
        breakdown = self.by_model()

        for model, stats in sorted(breakdown.items()):
            total = stats["total_tokens"]
            cost = stats["cost"]
            calls = stats["calls"]
            cost_str = f"${cost:.4f}" if cost > 0 else "$0.00"
            lines.append(f"  {model}: {total:,} tokens ({calls} calls) {cost_str}")

        lines.append("-" * 50)
        total_cost_str = f"${self.total_cost:.4f}" if self.total_cost > 0 else "$0.00"
        lines.append(
            f"  Total: {self.total_tokens:,} tokens "
            f"({self.call_count} calls) {total_cost_str}"
        )

        return "\n".join(lines)

    def reset(self) -> None:
        """Clear all usage records."""
        self._records.clear()
