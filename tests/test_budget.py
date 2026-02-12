"""Tests for token budget management."""

from __future__ import annotations

from musonius.context.budget import (
    TokenBudgetManager,
    count_tokens,
    fits_budget,
    truncate_to_budget,
)


class TestTokenCounting:
    """Tests for token counting functions."""

    def test_count_tokens(self) -> None:
        """Should return a positive token count for non-empty text."""
        tokens = count_tokens("Hello, world!")
        assert tokens > 0

    def test_empty_string(self) -> None:
        """Should return 0 for empty string."""
        assert count_tokens("") == 0

    def test_fits_budget(self) -> None:
        """Should correctly check budget fit."""
        assert fits_budget("Hello", 100)
        assert not fits_budget("Hello " * 1000, 10)

    def test_truncate_to_budget(self) -> None:
        """Should truncate text to fit budget."""
        long_text = "word " * 500
        truncated = truncate_to_budget(long_text, 50)
        assert count_tokens(truncated) <= 50

    def test_truncate_short_text(self) -> None:
        """Should not truncate text that fits."""
        text = "Hello, world!"
        result = truncate_to_budget(text, 1000)
        assert result == text


class TestTokenBudgetManager:
    """Tests for the TokenBudgetManager class."""

    def test_allocate(self) -> None:
        """Should allocate budget fractions."""
        mgr = TokenBudgetManager(10000)
        repo_budget = mgr.allocate("repo_map", 0.7)
        memory_budget = mgr.allocate("memory", 0.3)

        assert repo_budget == 7000
        assert memory_budget == 3000

    def test_record_and_remaining(self) -> None:
        """Should track usage against allocation."""
        mgr = TokenBudgetManager(10000)
        mgr.allocate("repo_map", 0.7)
        mgr.record_usage("repo_map", 3000)

        assert mgr.remaining("repo_map") == 4000
        assert mgr.total_used == 3000
        assert mgr.total_remaining == 7000
