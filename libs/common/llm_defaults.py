from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_llm_defaults() -> dict[str, dict[str, Any]]:
    defaults_path = Path(__file__).with_name("llm_defaults.json")
    defaults = json.loads(defaults_path.read_text())
    overrides_path = os.getenv("LLM_OVERRIDES_PATH") or os.getenv("LLM_CONFIG_PATH")
    if overrides_path:
        overrides = _load_overrides(Path(overrides_path))
        _apply_overrides(defaults, overrides)
    else:
        local_overrides = defaults_path.with_name("llm_overrides.json")
        if local_overrides.exists():
            overrides = _load_overrides(local_overrides)
            _apply_overrides(defaults, overrides)
    env_api_url = os.getenv("LLM_API_URL")
    env_model = os.getenv("LLM_MODEL")
    if env_api_url or env_model:
        for agent_type, config in defaults.items():
            if env_api_url:
                config["api_url"] = env_api_url
            if env_model:
                config["model"] = env_model
    return defaults


def _load_overrides(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _apply_overrides(
    defaults: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> None:
    for agent_type, override in overrides.items():
        if agent_type not in defaults:
            continue
        for key, value in override.items():
            if value is not None:
                defaults[agent_type][key] = value
