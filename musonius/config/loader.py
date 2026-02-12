"""Configuration loader — reads and merges project config with defaults."""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

from musonius.config.defaults import CONFIG_FILE, DEFAULT_CONFIG, MUSONIUS_DIR

logger = logging.getLogger(__name__)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge override into base, returning a new dict.

    Args:
        base: Base configuration dictionary.
        override: Override values to merge on top.

    Returns:
        Merged configuration dictionary.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(project_root: Path) -> dict[str, Any]:
    """Load project configuration, merging with defaults.

    Args:
        project_root: Root directory of the project.

    Returns:
        Merged configuration dictionary.
    """
    config_path = project_root / MUSONIUS_DIR / CONFIG_FILE

    if not config_path.exists():
        logger.debug("No config file found at %s, using defaults", config_path)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        logger.warning("Failed to load config from %s: %s", config_path, e)
        return copy.deepcopy(DEFAULT_CONFIG)

    return deep_merge(DEFAULT_CONFIG, user_config)


def save_config(project_root: Path, config: dict[str, Any]) -> None:
    """Save configuration to the project's .musonius directory.

    Args:
        project_root: Root directory of the project.
        config: Configuration dictionary to save.
    """
    config_path = project_root / MUSONIUS_DIR / CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
