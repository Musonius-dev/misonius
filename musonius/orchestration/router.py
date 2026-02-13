"""Model Router — routes LLM calls via CLI tools first, LiteLLM as fallback.

Routing priority:
1. CLI tools (claude, gemini) — zero config, uses existing subscriptions
2. LiteLLM API — requires API keys in environment
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable

import litellm

from musonius.orchestration.cli_backend import call_cli, detect_cli_tools
from musonius.orchestration.usage import UsageTracker

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True

# Map model provider prefixes to the CLI tool that handles them
_PROVIDER_TO_CLI: dict[str, str] = {
    "anthropic": "claude",
    "gemini": "gemini",
    "google": "gemini",
}

# Map model provider prefixes to the env var that holds the API key
_PROVIDER_TO_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
}


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
    """Routes LLM calls with automatic backend selection.

    Priority order:
    1. If API key exists for the model's provider → use LiteLLM (direct API)
    2. If CLI tool exists for the model's provider → use CLI backend
    3. Fallback model if configured

    This means users with API keys get the full LiteLLM experience,
    and users without keys can still use their CLI subscriptions.

    Args:
        config: Project configuration dictionary.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.usage_tracker = UsageTracker()
        self._model_config = config.get("models", {})
        self._custom_models = self._build_custom_model_map()
        self._cli_tools = detect_cli_tools()

        if self._cli_tools:
            logger.info(
                "Detected CLI tools: %s",
                ", ".join(self._cli_tools.keys()),
            )

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

    def _get_provider(self, model: str) -> str:
        """Extract the provider prefix from a model string.

        Args:
            model: Model identifier (e.g., "anthropic/claude-sonnet-4-20250514").

        Returns:
            Provider string (e.g., "anthropic"), or empty string.
        """
        if "/" in model:
            return model.split("/")[0]
        return ""

    def _has_api_key(self, model: str) -> bool:
        """Check if we should attempt a LiteLLM API call for this model.

        For models with a known provider prefix (anthropic/, gemini/), checks
        the corresponding environment variable. For unknown providers or models
        without a prefix, returns True so LiteLLM can attempt its own key
        resolution (e.g., OPENAI_API_KEY for gpt-4o).

        Args:
            model: Model identifier.

        Returns:
            True if we should attempt a LiteLLM call.
        """
        provider = self._get_provider(model)
        env_var = _PROVIDER_TO_KEY_ENV.get(provider, "")
        if env_var:
            return bool(os.environ.get(env_var))
        # Unknown provider — let LiteLLM try (it may resolve the key itself)
        return True

    def _get_cli_tool_for_model(self, model: str) -> str | None:
        """Get the CLI tool name that can handle this model, if available.

        Args:
            model: Model identifier.

        Returns:
            CLI tool name ("claude" or "gemini"), or None if unavailable.
        """
        provider = self._get_provider(model)
        cli_name = _PROVIDER_TO_CLI.get(provider)
        if cli_name and cli_name in self._cli_tools:
            return cli_name
        return None

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
        on_status: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Call an LLM with automatic backend selection.

        Tries in order:
        1. LiteLLM (if API key exists for the provider)
        2. CLI backend (if CLI tool is installed)
        3. Fallback model (if configured)

        Args:
            model: Model identifier (e.g., "anthropic/claude-sonnet-4-20250514").
            messages: Chat messages in OpenAI format.
            temperature: Sampling temperature.
            max_tokens: Maximum response tokens.
            retries: Number of retry attempts.
            fallback_model: Fallback model if primary fails.
            on_status: Optional callback for progress status updates.
            **kwargs: Additional parameters passed to litellm.completion.

        Returns:
            ModelResponse with content and usage.

        Raises:
            RuntimeError: If all attempts and fallback fail.
        """
        last_error: Exception | None = None

        def _status(msg: str) -> None:
            if on_status:
                on_status(msg)

        # Strategy 1: Try LiteLLM if we have an API key
        if self._has_api_key(model):
            _status(f"Calling {model} via API...")
            for attempt in range(retries + 1):
                try:
                    return self._make_litellm_call(model, messages, temperature, max_tokens, **kwargs)
                except Exception as e:
                    last_error = e
                    _status(f"API attempt {attempt + 1}/{retries + 1} failed")
                    logger.warning(
                        "LiteLLM call failed (attempt %d/%d) for %s: %s",
                        attempt + 1,
                        retries + 1,
                        model,
                        e,
                    )
                    if attempt < retries:
                        base_delay = 2**attempt
                        jitter = random.uniform(0, base_delay * 0.5)
                        _status(f"Retrying in {base_delay:.0f}s...")
                        time.sleep(base_delay + jitter)

        # Strategy 2: Try CLI backend
        cli_tool = self._get_cli_tool_for_model(model)
        if cli_tool:
            _status(f"Routing to {cli_tool} CLI...")
            try:
                return self._make_cli_call(cli_tool, model, messages, max_tokens)
            except Exception as e:
                last_error = e
                _status(f"{cli_tool} CLI failed: {e}")
                logger.warning("CLI call failed for %s via %s: %s", model, cli_tool, e)

        # Strategy 3: Try fallback model (recurse with fallback)
        if fallback_model and fallback_model != model:
            _status(f"Falling back to {fallback_model}...")
            logger.info("Falling back from %s to %s", model, fallback_model)
            try:
                return self.call(
                    fallback_model, messages, temperature, max_tokens,
                    retries=retries, fallback_model=None, on_status=on_status,
                    **kwargs,
                )
            except Exception as e:
                logger.error("Fallback model %s also failed: %s", fallback_model, e)
                last_error = e

        # Build helpful error message
        error_parts = [f"All model call attempts failed for {model}."]
        if not self._has_api_key(model):
            provider = self._get_provider(model)
            env_var = _PROVIDER_TO_KEY_ENV.get(provider, f"{provider.upper()}_API_KEY")
            error_parts.append(f"No API key found (set {env_var}).")
        if not cli_tool:
            provider = self._get_provider(model)
            cli_name = _PROVIDER_TO_CLI.get(provider, "unknown")
            error_parts.append(f"No '{cli_name}' CLI found in PATH.")
        error_parts.append("Install a CLI tool or set an API key.")

        raise RuntimeError(" ".join(error_parts)) from last_error

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
        # If planner is anthropic and no key, try gemini as fallback
        fallback = self.get_model("scout")
        return self.call(model, messages, fallback_model=fallback, **kwargs)

    def call_verifier(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> ModelResponse:
        """Call the verifier model (cross-model review).

        Falls back to scout model if verifier is unavailable.

        Args:
            messages: Chat messages.
            **kwargs: Additional parameters.

        Returns:
            ModelResponse from the verifier model.
        """
        model = self.get_model("verifier")
        fallback = self.get_model("scout")
        return self.call(model, messages, fallback_model=fallback, **kwargs)

    def _make_cli_call(
        self,
        cli_tool: str,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """Make an LLM call via a CLI tool.

        Args:
            cli_tool: CLI tool name ("claude" or "gemini").
            model: Original model identifier (for tracking).
            messages: Chat messages.
            max_tokens: Maximum response tokens.

        Returns:
            ModelResponse from the CLI tool.
        """
        logger.info("Routing %s via %s CLI", model, cli_tool)
        result = call_cli(cli_tool, messages, max_tokens=max_tokens)

        content = result["content"]
        latency_ms = result.get("latency_ms", 0.0)

        # Rough token estimation for CLI calls (no exact count available)
        prompt_text = " ".join(m.get("content", "") for m in messages)
        est_prompt_tokens = len(prompt_text) // 4
        est_completion_tokens = len(content) // 4

        self.usage_tracker.record(
            model=f"{cli_tool}-cli",
            prompt_tokens=est_prompt_tokens,
            completion_tokens=est_completion_tokens,
            cost=0.0,  # CLI uses existing subscription
        )

        return ModelResponse(
            content=content,
            model=f"{cli_tool}-cli",
            prompt_tokens=est_prompt_tokens,
            completion_tokens=est_completion_tokens,
            cost=0.0,
            latency_ms=latency_ms,
        )

    def _make_litellm_call(
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
