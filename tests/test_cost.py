"""Tests for cost estimation and persistent cost tracking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from musonius.orchestration.cost import (
    CostEstimate,
    CostRecord,
    CostTracker,
    estimate_cost,
    format_cost,
)


class TestCostEstimate:
    """Tests for pre-call cost estimation."""

    def test_estimate_free_tier(self) -> None:
        """Free-tier models should have zero cost."""
        est = estimate_cost("plan", "gemini/gemini-2.0-flash", input_tokens=5000)
        assert est.estimated_cost_usd == 0.0
        assert est.is_free_tier is True

    def test_estimate_premium_model(self) -> None:
        """Premium models should have non-zero cost."""
        est = estimate_cost(
            "plan",
            "anthropic/claude-sonnet-4-20250514",
            input_tokens=5000,
            output_tokens=2500,
        )
        assert est.estimated_cost_usd > 0.0
        assert est.is_free_tier is False

    def test_estimate_auto_output_tokens(self) -> None:
        """Should auto-estimate output tokens based on operation."""
        est = estimate_cost("plan", "gpt-4o", input_tokens=10000)
        # Plan ratio is 0.5 → 5000 output tokens
        assert est.estimated_output_tokens == 5000

    def test_estimate_verify_ratio(self) -> None:
        """Verify should use 0.3 output ratio."""
        est = estimate_cost("verify", "gpt-4o", input_tokens=10000)
        assert est.estimated_output_tokens == 3000

    def test_estimate_scout_ratio(self) -> None:
        """Scout should use 0.2 output ratio."""
        est = estimate_cost("scout", "gpt-4o", input_tokens=10000)
        assert est.estimated_output_tokens == 2000

    def test_estimate_unknown_model(self) -> None:
        """Unknown models should fall back to premium pricing."""
        est = estimate_cost("plan", "unknown/model-x", input_tokens=1000, output_tokens=500)
        assert est.estimated_cost_usd > 0.0
        assert est.is_free_tier is False

    def test_estimate_fields(self) -> None:
        """Estimate should have all expected fields."""
        est = estimate_cost("plan", "gpt-4o-mini", input_tokens=1000, output_tokens=500)
        assert est.operation == "plan"
        assert est.model == "gpt-4o-mini"
        assert est.estimated_input_tokens == 1000
        assert est.estimated_output_tokens == 500
        assert isinstance(est.estimated_cost_usd, float)


class TestCostTracker:
    """Tests for persistent cost tracking."""

    def test_record_and_summary(self, tmp_path: Path) -> None:
        """Should record costs and generate summary."""
        tracker = CostTracker(tmp_path)
        (tmp_path / ".musonius" / "memory").mkdir(parents=True)

        tracker.record(CostRecord(
            operation="plan",
            model="anthropic/claude-sonnet-4-20250514",
            input_tokens=5000,
            output_tokens=2500,
            cost_usd=0.05,
        ))
        tracker.record(CostRecord(
            operation="verify",
            model="gemini/gemini-2.0-flash",
            input_tokens=3000,
            output_tokens=1000,
            cost_usd=0.0,
        ))

        summary = tracker.get_summary()
        assert summary.total_cost_usd == 0.05
        assert summary.total_tokens == 11500
        assert len(summary.operations) == 2
        assert len(summary.models) == 2
        assert summary.operations["plan"]["calls"] == 1
        assert summary.operations["verify"]["calls"] == 1

    def test_persistence(self, tmp_path: Path) -> None:
        """Should persist records across instances."""
        (tmp_path / ".musonius" / "memory").mkdir(parents=True)

        tracker1 = CostTracker(tmp_path)
        tracker1.record(CostRecord(
            operation="plan", model="gpt-4o", input_tokens=1000,
            output_tokens=500, cost_usd=0.01,
        ))

        # New instance should load existing records
        tracker2 = CostTracker(tmp_path)
        summary = tracker2.get_summary()
        assert summary.total_cost_usd == 0.01
        assert summary.total_tokens == 1500

    def test_free_tier_savings(self, tmp_path: Path) -> None:
        """Should calculate savings from free-tier usage."""
        (tmp_path / ".musonius" / "memory").mkdir(parents=True)

        tracker = CostTracker(tmp_path)
        tracker.record(CostRecord(
            operation="scout",
            model="gemini/gemini-2.0-flash",
            input_tokens=10000,
            output_tokens=2000,
            cost_usd=0.0,
        ))

        summary = tracker.get_summary()
        assert summary.free_tier_savings > 0.0

    def test_empty_summary(self, tmp_path: Path) -> None:
        """Empty tracker should return zeroed summary."""
        tracker = CostTracker(tmp_path)
        summary = tracker.get_summary()
        assert summary.total_cost_usd == 0.0
        assert summary.total_tokens == 0
        assert len(summary.operations) == 0

    def test_corrupted_file(self, tmp_path: Path) -> None:
        """Should handle corrupted cost file gracefully."""
        memory_dir = tmp_path / ".musonius" / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "costs.json").write_text("not valid json{{{")

        tracker = CostTracker(tmp_path)
        summary = tracker.get_summary()
        assert summary.total_cost_usd == 0.0


class TestFormatCost:
    """Tests for cost formatting."""

    def test_free_tier(self) -> None:
        assert format_cost(0.0) == "$0.00 (free tier)"

    def test_small_cost(self) -> None:
        assert format_cost(0.0015) == "$0.0015"

    def test_normal_cost(self) -> None:
        assert format_cost(1.50) == "$1.50"
