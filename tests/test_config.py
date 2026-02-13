"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from musonius.config.defaults import DEFAULT_CONFIG, generate_optimal_models
from musonius.config.loader import deep_merge, load_config, save_config
from musonius.orchestration.cli_backend import CLITool


class TestDeepMerge:
    """Tests for deep_merge function."""

    def test_simple_merge(self) -> None:
        """Should merge simple dicts."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        """Should deep-merge nested dicts."""
        base = {"models": {"scout": "flash", "planner": "sonnet"}}
        override = {"models": {"scout": "pro"}}
        result = deep_merge(base, override)
        assert result["models"]["scout"] == "pro"
        assert result["models"]["planner"] == "sonnet"

    def test_does_not_modify_base(self) -> None:
        """Should not modify the base dict."""
        base = {"a": {"b": 1}}
        override = {"a": {"b": 2}}
        deep_merge(base, override)
        assert base["a"]["b"] == 1


class TestConfigLoader:
    """Tests for config loading and saving."""

    def test_load_defaults(self, tmp_path: Path) -> None:
        """Should return defaults when no config file exists."""
        config = load_config(tmp_path)
        assert config["default_agent"] == "claude"
        assert "models" in config

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Should round-trip save and load."""
        config = DEFAULT_CONFIG.copy()
        config["default_agent"] = "gemini"

        save_config(tmp_path, config)
        loaded = load_config(tmp_path)
        assert loaded["default_agent"] == "gemini"

    def test_user_config_overrides(self, tmp_path: Path) -> None:
        """Should merge user config with defaults."""
        musonius_dir = tmp_path / ".musonius"
        musonius_dir.mkdir()
        config_path = musonius_dir / "config.yaml"

        user_config = {"models": {"scout": "custom/model"}, "default_agent": "gemini"}
        with open(config_path, "w") as f:
            yaml.dump(user_config, f)

        loaded = load_config(tmp_path)
        assert loaded["models"]["scout"] == "custom/model"
        assert loaded["models"]["planner"] == DEFAULT_CONFIG["models"]["planner"]
        assert loaded["default_agent"] == "gemini"


class TestGenerateOptimalModels:
    """Tests for generate_optimal_models auto-config."""

    def test_claude_only_cli(self) -> None:
        """Claude CLI only: remap cheap roles to Anthropic Haiku."""
        tools = {"claude": CLITool(name="claude", command="/usr/bin/claude", provider="anthropic")}
        with patch.dict("os.environ", {}, clear=True):
            models = generate_optimal_models(tools)
        assert "anthropic" in models["scout"]
        assert "anthropic" in models["verifier"]
        assert "anthropic" in models["summarizer"]
        # Planner should remain anthropic
        assert "anthropic" in models["planner"]

    def test_gemini_only_cli(self) -> None:
        """Gemini CLI only: remap planner to Gemini."""
        tools = {"gemini": CLITool(name="gemini", command="/usr/bin/gemini", provider="google")}
        with patch.dict("os.environ", {}, clear=True):
            models = generate_optimal_models(tools)
        assert "gemini" in models["planner"]
        # Scout/verifier should stay as gemini defaults
        assert "gemini" in models["scout"]
        assert "gemini" in models["verifier"]

    def test_both_tools_keeps_defaults(self) -> None:
        """Both CLI tools: keep default config (best of both)."""
        tools = {
            "claude": CLITool(name="claude", command="/usr/bin/claude", provider="anthropic"),
            "gemini": CLITool(name="gemini", command="/usr/bin/gemini", provider="google"),
        }
        with patch.dict("os.environ", {}, clear=True):
            models = generate_optimal_models(tools)
        assert models["scout"] == DEFAULT_CONFIG["models"]["scout"]
        assert models["planner"] == DEFAULT_CONFIG["models"]["planner"]
        assert models["verifier"] == DEFAULT_CONFIG["models"]["verifier"]

    def test_no_tools_returns_defaults(self) -> None:
        """No tools or keys: return defaults (router will handle errors)."""
        with patch.dict("os.environ", {}, clear=True):
            models = generate_optimal_models({})
        assert models["scout"] == DEFAULT_CONFIG["models"]["scout"]
        assert models["planner"] == DEFAULT_CONFIG["models"]["planner"]

    def test_anthropic_api_key_overrides_planner(self) -> None:
        """ANTHROPIC_API_KEY present: ensure planner stays anthropic."""
        tools = {"gemini": CLITool(name="gemini", command="/usr/bin/gemini", provider="google")}
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            models = generate_optimal_models(tools)
        assert models["planner"] == DEFAULT_CONFIG["models"]["planner"]

    def test_gemini_api_key_overrides_scout(self) -> None:
        """GEMINI_API_KEY present: ensure scout/verifier stay gemini."""
        tools = {"claude": CLITool(name="claude", command="/usr/bin/claude", provider="anthropic")}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "gk-test"}, clear=True):
            models = generate_optimal_models(tools)
        assert models["scout"] == DEFAULT_CONFIG["models"]["scout"]
        assert models["verifier"] == DEFAULT_CONFIG["models"]["verifier"]

    def test_both_api_keys(self) -> None:
        """Both API keys: should match defaults."""
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_API_KEY": "sk-test", "GEMINI_API_KEY": "gk-test"},
            clear=True,
        ):
            models = generate_optimal_models({})
        assert models["planner"] == DEFAULT_CONFIG["models"]["planner"]
        assert models["scout"] == DEFAULT_CONFIG["models"]["scout"]
        assert models["verifier"] == DEFAULT_CONFIG["models"]["verifier"]
