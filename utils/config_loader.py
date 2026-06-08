"""Configuration loader with environment variable substitution."""

import os
import re
from pathlib import Path
from typing import Any

import yaml


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: Any) -> Any:
    """Recursively resolve ${ENV_VAR} placeholders in config values."""
    if isinstance(value, str):
        def replacer(match):
            env_var = match.group(1)
            return os.environ.get(env_var, match.group(0))
        return _ENV_VAR_PATTERN.sub(replacer, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def load_config(config_path: str = "config.yaml") -> dict:
    """Load and validate the YAML configuration file.

    Args:
        config_path: Path to config.yaml. Defaults to 'config.yaml' in CWD.

    Returns:
        Parsed and resolved configuration dictionary.

    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If required fields are missing.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path.absolute()}")

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if config is None:
        raise ValueError(f"Config file {path.absolute()} is empty")

    # Resolve environment variables
    config = _resolve_env_vars(config)

    # Validate required sections
    _validate(config, path)

    return config


def _validate(config: dict, path: Path) -> None:
    """Validate that required configuration sections and fields exist.

    Note: api_key and chat_id are validated at runtime in main.py,
    not here, to allow the project to be set up incrementally.
    """
    errors = []

    if "feishu" not in config:
        errors.append("Missing 'feishu' section")
    else:
        feishu = config["feishu"]
        if not feishu.get("app_id"):
            errors.append("feishu.app_id is required")
        if not feishu.get("app_secret"):
            errors.append("feishu.app_secret is required")

    # Support both 'llm' (new) and 'anthropic' (legacy) sections
    if "llm" not in config and "anthropic" not in config:
        errors.append("Missing 'llm' section (or legacy 'anthropic' section)")

    if "sources" not in config:
        errors.append("Missing 'sources' section")

    if errors:
        raise ValueError(
            f"Configuration errors in {path.absolute()}:\n  "
            + "\n  ".join(errors)
        )
