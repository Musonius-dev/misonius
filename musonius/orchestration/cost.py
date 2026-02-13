"""Cost estimation and persistent cost tracking for Musonius operations.

Provides pre-call cost estimates and session-persistent cost records
stored in the .musonius/ directory.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (input, output) — updated Feb 2025
# Source: provider pricing pages. Used for estimation only.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "anthropic/claude-sonnet-4-20250514": (3.00, 15.00),
    "anthropic/claude-opus-4-20250514": (15.00, 75.00),
    "anthropic/claude-haiku-3-5-20241022": (0.80, 4.00),
    # Google (Gemini Flash is free tier up to limits)
    "gemini/gemini-2.0-flash": (0.0, 0.0),
    "gemini/gemini-2.0-flash-lite": (0.0, 0.0),
    "gemini/gemini-1.5-pro": (1.25, 5.00),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    # Ollama (local, free)
    "ollama/llama3.2": (0.0, 0.0),
    "ollama/mistral": (0.0, 0.0),
    "ollama/codellama": (0.0, 0.0),
}


@dataclass
class CostEstimate:
    """Pre-call cost estimate for a Musonius operation.

    Attributes:
        operation: The operation being estimated (plan, verify, prep).
        model: Model that will be used.
        estimated_input_tokens: Estimated prompt tokens.
        estimated_output_tokens: Estimated completion tokens.
        estimated_cost_usd: Estimated total cost in USD.
        is_free_tier: Whether this model is free.
    """

    operation: str
    model: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    is_free_tier: bool = False


@dataclass
class CostRecord:
    """A recorded cost from an actual operation.

    Attributes:
        operation: The operation that ran.
        model: Model used.
        input_tokens: Actual prompt tokens.
        output_tokens: Actual completion tokens.
        cost_usd: Actual cost.
        timestamp: When the call was made.
    """

    operation: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class CostSummary:
    """Aggregated cost summary across sessions.

    Attributes:
        total_cost_usd: Total spend across all operations.
        total_tokens: Total tokens consumed.
        operations: Per-operation breakdown.
        models: Per-model breakdown.
        free_tier_savings: Estimated savings from free-tier routing.
    """

    total_cost_usd: float = 0.0
    total_tokens: int = 0
    operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    free_tier_savings: float = 0.0


class CostTracker:
    """Persistent cost tracking across Musonius sessions.

    Stores cost records in .musonius/memory/costs.json so users can
    track their spending over time.

    Args:
        project_root: Project root directory.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._costs_path = project_root / ".musonius" / "memory" / "costs.json"
        self._records: list[CostRecord] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Load cost records from disk if not already loaded."""
        if self._loaded:
            return

        if self._costs_path.exists():
            try:
                data = json.loads(self._costs_path.read_text())
                self._records = [
                    CostRecord(**r) for r in data.get("records", [])
                ]
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Failed to load cost records: %s", e)
                self._records = []

        self._loaded = True

    def record(self, record: CostRecord) -> None:
        """Record a cost from an actual operation.

        Args:
            record: The cost record to store.
        """
        self._ensure_loaded()
        self._records.append(record)
        self._save()

    def _save(self) -> None:
        """Persist cost records to disk."""
        self._costs_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"records": [asdict(r) for r in self._records]}
        self._costs_path.write_text(json.dumps(data, indent=2))

    def get_summary(self) -> CostSummary:
        """Get an aggregated cost summary.

        Returns:
            CostSummary with totals and breakdowns.
        """
        self._ensure_loaded()
        summary = CostSummary()

        for record in self._records:
            total_tokens = record.input_tokens + record.output_tokens
            summary.total_cost_usd += record.cost_usd
            summary.total_tokens += total_tokens

            # Per-operation breakdown
            if record.operation not in summary.operations:
                summary.operations[record.operation] = {
                    "calls": 0,
                    "tokens": 0,
                    "cost_usd": 0.0,
                }
            op = summary.operations[record.operation]
            op["calls"] += 1
            op["tokens"] += total_tokens
            op["cost_usd"] += record.cost_usd

            # Per-model breakdown
            if record.model not in summary.models:
                summary.models[record.model] = {
                    "calls": 0,
                    "tokens": 0,
                    "cost_usd": 0.0,
                }
            mdl = summary.models[record.model]
            mdl["calls"] += 1
            mdl["tokens"] += total_tokens
            mdl["cost_usd"] += record.cost_usd

            # Track free tier savings
            if record.cost_usd == 0.0 and total_tokens > 0:
                # Estimate what this would have cost on a paid model
                premium_rate = 3.0 / 1_000_000  # ~$3/M tokens average
                summary.free_tier_savings += total_tokens * premium_rate

        return summary


def estimate_cost(
    operation: str,
    model: str,
    input_tokens: int,
    output_tokens: int = 0,
) -> CostEstimate:
    """Estimate the cost of an operation before running it.

    Args:
        operation: Operation name (plan, verify, prep, scout).
        model: Model identifier.
        input_tokens: Estimated prompt tokens.
        output_tokens: Estimated completion tokens (0 = auto-estimate).

    Returns:
        CostEstimate with projected cost.
    """
    # Auto-estimate output tokens based on operation type
    if output_tokens == 0:
        output_ratios = {
            "plan": 0.5,      # Plans are ~50% of input length
            "verify": 0.3,    # Verification reports are shorter
            "scout": 0.2,     # Scout responses are brief
            "prep": 0.0,      # Prep doesn't use LLM
        }
        ratio = output_ratios.get(operation, 0.3)
        output_tokens = int(input_tokens * ratio)

    # Look up pricing
    pricing = MODEL_PRICING.get(model, (5.0, 15.0))  # Default to premium pricing
    input_price_per_m, output_price_per_m = pricing

    is_free = input_price_per_m == 0.0 and output_price_per_m == 0.0
    cost = (
        (input_tokens * input_price_per_m / 1_000_000)
        + (output_tokens * output_price_per_m / 1_000_000)
    )

    return CostEstimate(
        operation=operation,
        model=model,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_cost_usd=round(cost, 6),
        is_free_tier=is_free,
    )


def format_cost(cost_usd: float) -> str:
    """Format a cost for display.

    Args:
        cost_usd: Cost in USD.

    Returns:
        Formatted cost string.
    """
    if cost_usd == 0.0:
        return "$0.00 (free tier)"
    elif cost_usd < 0.01:
        return f"${cost_usd:.4f}"
    else:
        return f"${cost_usd:.2f}"
