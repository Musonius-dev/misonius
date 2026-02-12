"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import yaml

from musonius.config.defaults import DEFAULT_CONFIG
from musonius.config.loader import deep_merge, load_config, save_config


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
