"""Model Router — routes LLM calls via LiteLLM with retry and fallback."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import litellm

from musonius.orchestration.usage import UsageTracker

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


@dataclass
class ModelResponse:
    """Response from a model call.

    Attributes:
        content: The text content of the response.
        model: Model identifier that was actually used.
        prompt_tokens: Number of prompt tokens used.
        completion_tokens: Number of completion tokens generated.
        cost: Estimated cost in USD.
        latency_ms: Response time in milliseconds.
    """

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0


class ModelRouter:
    """Routes LLM calls via LiteLLM with retry logic, fallback, and usage tracking.

    Supports custom model definitions and API key resolution from config or
    environment variables.

    Args:
        config: Project configuration dictionary.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.usage_tracker = UsageTracker()
        self._model_config = config.get("models", {})
        self._custom_models = self._build_custom_model_map()

    def _build_custom_model_map(self) -> dict[str, dict[str, Any]]:
        """Build a lookup map from custom model definitions in config.

        Returns:
            Dict mapping custom model name to its provider/model/api config.
        """
        custom_list = self._model_config.get("custom", [])
        result: dict[str, dict[str, Any]] = {}
        for entry in custom_list:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not name:
                continue
            result[name] = entry
        return result

    def resolve_model(self, model: str) -> tuple[str, dict[str, Any]]:
        """Resolve a model name to a LiteLLM-compatible identifier and extra kwargs.

        Handles custom model definitions by mapping short names to full
        provider/model strings and injecting api_base/api_key as needed.

        Args:
            model: Model name — either a LiteLLM identifier or a custom name.

        Returns:
            Tuple of (litellm_model_string, extra_kwargs).
        """
        if model not in self._custom_models:
            return model, {}

        custom = self._custom_models[model]
        provider = custom.get("provider", "")
        model_id = custom.get("model", model)
        litellm_model = f"{provider}/{model_id}" if provider else model_id

        extra: dict[str, Any] = {}
        if "api_base" in custom:
            extra["api_base"] = custom["api_base"]

        api_key_env = custom.get("api_key_env")
        if api_key_env:
            api_key = os.environ.get(api_key_env, "")
            if api_key:
                extra["api_key"] = api_key
            else:
                logger.warning(
                    "Environment variable %s not set for custom model %s",
                    api_key_env,
                    model,
                )

        return litellm_model, extra

    def get_model(self, role: str) -> str:
        """Get the configured model for a given role.

        Args:
            role: Model role (scout, planner, verifier, summarizer).

        Returns:
            Model identifier string.
        """
        result: str = self._model_config.get(role, self._model_config.get("planner", "gpt-4o-mini"))
        return result

    def call(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        retries: int = 2,
        fallback_model: str | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Call an LLM via LiteLLM with retry and fallback support.

        Args:
            model: Model identifier (e.g., "anthropic/claude-sonnet-4-20250514").
            messages: Chat messages in OpenAI format.
            temperature: Sampling temperature.
            max_tokens: Maximum response tokens.
            retries: Number of retry attempts.
            fallback_model: Fallback model if primary fails.
            **kwargs: Additional parameters passed to litellm.completion.

        Returns:
            ModelResponse with content and usage.

        Raises:
            RuntimeError: If all attempts and fallback fail.
        """
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                return self._make_call(model, messages, temperature, max_tokens, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(
                    "Model call failed (attempt %d/%d) for %s: %s",
                    attempt + 1,
                    retries + 1,
                    model,
                    e,
                )
                if attempt < retries:
                    time.sleep(2**attempt)

        # Try fallback model
        if fallback_model and fallback_model != model:
            logger.info("Falling back to %s", fallback_model)
            try:
                return self._make_call(
                    fallback_model, messages, temperature, max_tokens, **kwargs
                )
            except Exception as e:
                logger.error("Fallback model %s also failed: %s", fallback_model, e)

        raise RuntimeError(
            f"All model call attempts failed for {model}: {last_error}"
        ) from last_error

    def call_scout(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> ModelResponse:
        """Call the scout model (free/cheap tier).

        Args:
            messages: Chat messages.
            **kwargs: Additional parameters.

        Returns:
            ModelResponse from the scout model.
        """
        model = self.get_model("scout")
        fallback = self.get_model("summarizer")
        return self.call(model, messages, fallback_model=fallback, **kwargs)

    def call_planner(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> ModelResponse:
        """Call the planner model (premium tier).

        Args:
            messages: Chat messages.
            **kwargs: Additional parameters.

        Returns:
            ModelResponse from the planner model.
        """
        model = self.get_model("planner")
        return self.call(model, messages, **kwargs)

    def call_verifier(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> ModelResponse:
        """Call the verifier model (cross-model review).

        Args:
            messages: Chat messages.
            **kwargs: Additional parameters.

        Returns:
            ModelResponse from the verifier model.
        """
        model = self.get_model("verifier")
        return self.call(model, messages, **kwargs)

    def _make_call(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Make a single LLM call via litellm."""
        resolved_model, custom_kwargs = self.resolve_model(model)
        start = time.monotonic()

        call_kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            call_kwargs["max_tokens"] = max_tokens
        # Custom model kwargs first, then caller kwargs (caller wins on conflict)
        call_kwargs.update(custom_kwargs)
        call_kwargs.update(kwargs)

        response = litellm.completion(**call_kwargs)

        elapsed_ms = (time.monotonic() - start) * 1000

        content = response.choices[0].message.content or ""
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        try:
            cost = litellm.completion_cost(completion_response=response)
        except Exception:
            cost = 0.0

        self.usage_tracker.record(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
        )

        return ModelResponse(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            latency_ms=elapsed_ms,
        )
