"""Tests for the model router and usage tracker."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from musonius.orchestration.router import ModelResponse, ModelRouter
from musonius.orchestration.usage import UsageTracker

# Fake API keys so the router uses LiteLLM path in tests
_FAKE_ENV = {
    "ANTHROPIC_API_KEY": "sk-test-fake",
    "GEMINI_API_KEY": "test-gemini-key",
    "OPENAI_API_KEY": "sk-test-openai",
}


def _make_litellm_response(
    content: str = "Hello!",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> SimpleNamespace:
    """Build a fake LiteLLM completion response."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


# ---------------------------------------------------------------------------
# UsageTracker
# ---------------------------------------------------------------------------


class TestUsageTracker:
    """Tests for the UsageTracker class."""

    def test_record_usage(self) -> None:
        """Should record token usage."""
        tracker = UsageTracker()
        tracker.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50, cost=0.01)

        assert tracker.total_tokens == 150
        assert tracker.total_prompt_tokens == 100
        assert tracker.total_completion_tokens == 50
        assert tracker.total_cost == 0.01
        assert tracker.call_count == 1

    def test_multiple_records(self) -> None:
        """Should accumulate across multiple calls."""
        tracker = UsageTracker()
        tracker.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50, cost=0.01)
        tracker.record(model="gpt-4o-mini", prompt_tokens=200, completion_tokens=100, cost=0.005)

        assert tracker.total_tokens == 450
        assert tracker.call_count == 2
        assert tracker.total_cost == pytest.approx(0.015)

    def test_by_model(self) -> None:
        """Should break down usage by model."""
        tracker = UsageTracker()
        tracker.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50, cost=0.01)
        tracker.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50, cost=0.01)
        tracker.record(model="gemini-flash", prompt_tokens=200, completion_tokens=100, cost=0.0)

        breakdown = tracker.by_model()
        assert "gpt-4o" in breakdown
        assert "gemini-flash" in breakdown
        assert breakdown["gpt-4o"]["calls"] == 2
        assert breakdown["gemini-flash"]["calls"] == 1

    def test_reset(self) -> None:
        """Should clear all records."""
        tracker = UsageTracker()
        tracker.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        tracker.reset()

        assert tracker.total_tokens == 0
        assert tracker.call_count == 0

    def test_report_empty(self) -> None:
        """Should return message when no calls recorded."""
        tracker = UsageTracker()
        assert tracker.report() == "No model calls recorded."

    def test_report_with_records(self) -> None:
        """Should generate formatted usage report."""
        tracker = UsageTracker()
        tracker.record(model="gemini/gemini-flash", prompt_tokens=500, completion_tokens=100, cost=0.0)
        tracker.record(model="anthropic/claude-sonnet", prompt_tokens=200, completion_tokens=80, cost=0.025)

        report = tracker.report()
        assert "Token Usage Report" in report
        assert "gemini/gemini-flash" in report
        assert "anthropic/claude-sonnet" in report
        assert "Total:" in report
        assert "$0.00" in report  # gemini is free
        assert "$0.0250" in report  # claude cost


# ---------------------------------------------------------------------------
# ModelResponse
# ---------------------------------------------------------------------------


class TestModelResponse:
    """Tests for the ModelResponse dataclass."""

    def test_defaults(self) -> None:
        """Should have sensible defaults."""
        resp = ModelResponse(content="hello", model="gpt-4o")
        assert resp.content == "hello"
        assert resp.prompt_tokens == 0
        assert resp.completion_tokens == 0
        assert resp.cost == 0.0
        assert resp.latency_ms == 0.0


# ---------------------------------------------------------------------------
# ModelRouter — initialization and config
# ---------------------------------------------------------------------------


class TestModelRouterConfig:
    """Tests for ModelRouter configuration resolution."""

    def test_get_model_returns_configured(self) -> None:
        """Should return the model for a known role."""
        config = {"models": {"scout": "gemini/gemini-2.0-flash", "planner": "claude-sonnet"}}
        router = ModelRouter(config)
        assert router.get_model("scout") == "gemini/gemini-2.0-flash"
        assert router.get_model("planner") == "claude-sonnet"

    def test_get_model_falls_back_to_planner(self) -> None:
        """Should fall back to planner when role is unknown."""
        config = {"models": {"planner": "claude-sonnet"}}
        router = ModelRouter(config)
        assert router.get_model("verifier") == "claude-sonnet"

    def test_get_model_ultimate_fallback(self) -> None:
        """Should use gpt-4o-mini when no config at all."""
        router = ModelRouter({})
        assert router.get_model("scout") == "gpt-4o-mini"

    def test_custom_model_map_built(self) -> None:
        """Should parse custom model definitions from config."""
        config = {
            "models": {
                "custom": [
                    {
                        "name": "local-llama",
                        "provider": "ollama",
                        "model": "llama3.2",
                    },
                    {
                        "name": "deepseek-r1",
                        "provider": "openai",
                        "model": "deepseek-reasoner",
                        "api_base": "https://api.deepseek.com/v1",
                        "api_key_env": "DEEPSEEK_API_KEY",
                    },
                ]
            }
        }
        router = ModelRouter(config)
        assert "local-llama" in router._custom_models
        assert "deepseek-r1" in router._custom_models

    def test_custom_model_skips_invalid_entries(self) -> None:
        """Should skip custom entries that are not dicts or lack name."""
        config = {
            "models": {
                "custom": [
                    "not-a-dict",
                    {"provider": "ollama"},  # no name
                    {"name": "valid", "provider": "ollama", "model": "llama3.2"},
                ]
            }
        }
        router = ModelRouter(config)
        assert len(router._custom_models) == 1
        assert "valid" in router._custom_models


# ---------------------------------------------------------------------------
# ModelRouter — resolve_model
# ---------------------------------------------------------------------------


class TestResolveModel:
    """Tests for custom model resolution."""

    def test_standard_model_passes_through(self) -> None:
        """Standard LiteLLM identifiers should pass through unchanged."""
        router = ModelRouter({})
        model, kwargs = router.resolve_model("gemini/gemini-2.0-flash")
        assert model == "gemini/gemini-2.0-flash"
        assert kwargs == {}

    def test_custom_model_resolved(self) -> None:
        """Custom model name should resolve to provider/model string."""
        config = {
            "models": {
                "custom": [
                    {"name": "local-llama", "provider": "ollama", "model": "llama3.2"},
                ]
            }
        }
        router = ModelRouter(config)
        model, kwargs = router.resolve_model("local-llama")
        assert model == "ollama/llama3.2"
        assert kwargs == {}

    def test_custom_model_with_api_base(self) -> None:
        """Custom model with api_base should include it in extra kwargs."""
        config = {
            "models": {
                "custom": [
                    {
                        "name": "deepseek",
                        "provider": "openai",
                        "model": "deepseek-reasoner",
                        "api_base": "https://api.deepseek.com/v1",
                    },
                ]
            }
        }
        router = ModelRouter(config)
        model, kwargs = router.resolve_model("deepseek")
        assert model == "openai/deepseek-reasoner"
        assert kwargs == {"api_base": "https://api.deepseek.com/v1"}

    def test_custom_model_with_api_key_env(self) -> None:
        """Custom model should resolve API key from environment variable."""
        config = {
            "models": {
                "custom": [
                    {
                        "name": "deepseek",
                        "provider": "openai",
                        "model": "deepseek-reasoner",
                        "api_key_env": "TEST_DEEPSEEK_KEY",
                    },
                ]
            }
        }
        router = ModelRouter(config)
        with patch.dict("os.environ", {"TEST_DEEPSEEK_KEY": "sk-test-123"}):
            model, kwargs = router.resolve_model("deepseek")
        assert kwargs["api_key"] == "sk-test-123"

    def test_custom_model_missing_env_var(self) -> None:
        """Should warn and omit api_key when env var is not set."""
        config = {
            "models": {
                "custom": [
                    {
                        "name": "deepseek",
                        "provider": "openai",
                        "model": "deepseek-reasoner",
                        "api_key_env": "NONEXISTENT_KEY_VAR",
                    },
                ]
            }
        }
        router = ModelRouter(config)
        with patch.dict("os.environ", {}, clear=False):
            # Ensure the key is NOT in the environment
            import os

            os.environ.pop("NONEXISTENT_KEY_VAR", None)
            model, kwargs = router.resolve_model("deepseek")
        assert "api_key" not in kwargs


# ---------------------------------------------------------------------------
# ModelRouter — call (with mocked litellm)
# ---------------------------------------------------------------------------


@patch("musonius.orchestration.router.detect_cli_tools", return_value={})
class TestModelRouterCall:
    """Tests for ModelRouter.call with mocked LiteLLM."""

    @patch("musonius.orchestration.router.litellm")
    def test_successful_call(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should return ModelResponse on success."""
        mock_litellm.completion.return_value = _make_litellm_response("Hi there")
        mock_litellm.completion_cost.return_value = 0.001

        router = ModelRouter({"models": {}})
        resp = router.call(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello"}],
        )

        assert resp.content == "Hi there"
        assert resp.model == "gpt-4o-mini"
        assert resp.prompt_tokens == 10
        assert resp.completion_tokens == 5
        assert resp.cost == 0.001
        assert resp.latency_ms > 0
        assert router.usage_tracker.total_tokens == 15

    @patch("musonius.orchestration.router.litellm")
    def test_retry_on_failure(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should retry and succeed on second attempt."""
        mock_litellm.completion.side_effect = [
            Exception("API error"),
            _make_litellm_response("Recovered"),
        ]
        mock_litellm.completion_cost.return_value = 0.0

        router = ModelRouter({"models": {}})
        resp = router.call(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello"}],
            retries=1,
        )

        assert resp.content == "Recovered"
        assert mock_litellm.completion.call_count == 2

    @patch("musonius.orchestration.router.litellm")
    def test_fallback_on_all_retries_exhausted(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should use fallback model when primary exhausts retries."""
        mock_litellm.completion.side_effect = [
            Exception("Fail 1"),
            Exception("Fail 2"),
            _make_litellm_response("Fallback response"),
        ]
        mock_litellm.completion_cost.return_value = 0.0

        router = ModelRouter({"models": {}})
        resp = router.call(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello"}],
            retries=1,
            fallback_model="gpt-4o-mini",
        )

        assert resp.content == "Fallback response"

    @patch("musonius.orchestration.router.litellm")
    def test_raises_when_all_fail(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should raise RuntimeError when all attempts and fallback fail."""
        mock_litellm.completion.side_effect = Exception("All broken")

        router = ModelRouter({"models": {}})
        with pytest.raises(RuntimeError, match="All model call attempts failed"):
            router.call(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Hello"}],
                retries=0,
            )

    @patch("musonius.orchestration.router.litellm")
    def test_raises_when_fallback_also_fails(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should raise RuntimeError when both primary and fallback fail."""
        mock_litellm.completion.side_effect = Exception("All broken")

        router = ModelRouter({"models": {}})
        with pytest.raises(RuntimeError, match="All model call attempts failed"):
            router.call(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Hello"}],
                retries=0,
                fallback_model="gpt-4o-mini",
            )

    @patch("musonius.orchestration.router.litellm")
    def test_cost_fallback_on_error(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should default cost to 0.0 when completion_cost raises."""
        mock_litellm.completion.return_value = _make_litellm_response()
        mock_litellm.completion_cost.side_effect = Exception("Unknown model")

        router = ModelRouter({"models": {}})
        resp = router.call(
            model="custom-model",
            messages=[{"role": "user", "content": "Hello"}],
        )

        assert resp.cost == 0.0

    @patch("musonius.orchestration.router.litellm")
    def test_custom_model_kwargs_injected(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should inject api_base from custom model config into litellm call."""
        mock_litellm.completion.return_value = _make_litellm_response()
        mock_litellm.completion_cost.return_value = 0.0

        config = {
            "models": {
                "custom": [
                    {
                        "name": "my-model",
                        "provider": "openai",
                        "model": "custom-v1",
                        "api_base": "https://my-api.example.com/v1",
                    },
                ]
            }
        }
        router = ModelRouter(config)
        router.call(
            model="my-model",
            messages=[{"role": "user", "content": "Hello"}],
        )

        call_kwargs = mock_litellm.completion.call_args
        assert call_kwargs.kwargs.get("model") or call_kwargs[1].get("model") == "openai/custom-v1"
        # Check api_base was passed
        all_kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert all_kwargs["api_base"] == "https://my-api.example.com/v1"


# ---------------------------------------------------------------------------
# ModelRouter — role-based convenience methods
# ---------------------------------------------------------------------------


@patch.dict("os.environ", _FAKE_ENV)
@patch("musonius.orchestration.router.detect_cli_tools", return_value={})
class TestModelRouterRoleMethods:
    """Tests for call_scout, call_planner, call_verifier."""

    @patch("musonius.orchestration.router.litellm")
    def test_call_scout(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should use configured scout model."""
        mock_litellm.completion.return_value = _make_litellm_response("Scout reply")
        mock_litellm.completion_cost.return_value = 0.0

        config = {"models": {"scout": "gemini/gemini-2.0-flash", "summarizer": "ollama/llama3.2"}}
        router = ModelRouter(config)
        resp = router.call_scout(messages=[{"role": "user", "content": "Hello"}])

        assert resp.content == "Scout reply"
        call_kwargs = mock_litellm.completion.call_args
        all_kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert all_kwargs["model"] == "gemini/gemini-2.0-flash"

    @patch("musonius.orchestration.router.litellm")
    def test_call_planner(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should use configured planner model."""
        mock_litellm.completion.return_value = _make_litellm_response("Plan")
        mock_litellm.completion_cost.return_value = 0.0

        config = {"models": {"planner": "anthropic/claude-sonnet-4-20250514"}}
        router = ModelRouter(config)
        resp = router.call_planner(messages=[{"role": "user", "content": "Plan this"}])

        assert resp.content == "Plan"

    @patch("musonius.orchestration.router.litellm")
    def test_call_verifier(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should use configured verifier model."""
        mock_litellm.completion.return_value = _make_litellm_response("Verified")
        mock_litellm.completion_cost.return_value = 0.0

        config = {"models": {"verifier": "gemini/gemini-2.0-flash"}}
        router = ModelRouter(config)
        resp = router.call_verifier(messages=[{"role": "user", "content": "Check this"}])

        assert resp.content == "Verified"

    @patch("musonius.orchestration.router.litellm")
    def test_scout_falls_back_to_summarizer(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Scout should use summarizer as fallback model."""
        mock_litellm.completion.side_effect = [
            Exception("Scout down"),
            Exception("Scout down again"),
            Exception("Scout down third"),
            _make_litellm_response("Summarizer reply"),
        ]
        mock_litellm.completion_cost.return_value = 0.0

        config = {"models": {"scout": "gemini/gemini-2.0-flash", "summarizer": "ollama/llama3.2"}}
        router = ModelRouter(config)
        resp = router.call_scout(messages=[{"role": "user", "content": "Hello"}])

        assert resp.content == "Summarizer reply"


# ---------------------------------------------------------------------------
# ModelRouter — usage tracking integration
# ---------------------------------------------------------------------------


@patch.dict("os.environ", _FAKE_ENV)
@patch("musonius.orchestration.router.detect_cli_tools", return_value={})
class TestModelRouterUsageTracking:
    """Tests for usage tracking across model calls."""

    @patch("musonius.orchestration.router.litellm")
    def test_tracks_usage_across_calls(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Usage tracker should accumulate across multiple calls."""
        mock_litellm.completion.return_value = _make_litellm_response(
            prompt_tokens=100, completion_tokens=50
        )
        mock_litellm.completion_cost.return_value = 0.01

        router = ModelRouter({"models": {}})
        router.call(model="gpt-4o", messages=[{"role": "user", "content": "A"}])
        router.call(model="gpt-4o", messages=[{"role": "user", "content": "B"}])

        assert router.usage_tracker.total_tokens == 300
        assert router.usage_tracker.call_count == 2
        assert router.usage_tracker.total_cost == pytest.approx(0.02)

    @patch("musonius.orchestration.router.litellm")
    def test_usage_report(self, mock_litellm: MagicMock, _mock_cli: MagicMock) -> None:
        """Should generate a readable usage report."""
        mock_litellm.completion.return_value = _make_litellm_response(
            prompt_tokens=500, completion_tokens=100
        )
        mock_litellm.completion_cost.return_value = 0.0

        router = ModelRouter({"models": {}})
        router.call(
            model="gemini/gemini-2.0-flash",
            messages=[{"role": "user", "content": "Hello"}],
        )

        report = router.usage_tracker.report()
        assert "Token Usage Report" in report
        assert "gemini/gemini-2.0-flash" in report
        assert "600" in report  # 500 + 100
