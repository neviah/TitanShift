from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class ConfigManager:
    """Merges default config, file config, env vars, and runtime overrides."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        defaults_file = workspace_root / "harness" / "config_defaults.json"
        if not defaults_file.exists():
            # Fallback for installed package usage outside the source checkout.
            defaults_file = Path(__file__).resolve().parents[1] / "config_defaults.json"
        self._defaults = self._load_json(defaults_file)
        self._file_config = self._load_json(workspace_root / "harness.config.json")
        self._overrides: dict[str, Any] = {}

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def get(self, key: str, default: Any = None) -> Any:
        env_key = "HARNESS_" + key.upper().replace(".", "_")
        if env_key in os.environ:
            return os.environ[env_key]
        if key in self._overrides:
            return self._overrides[key]
        file_value = self._resolve_dot(self._file_config, key)
        if file_value is not None:
            return file_value
        default_value = self._resolve_dot(self._defaults, key)
        if default_value is not None:
            return default_value
        return default

    def set(self, key: str, value: Any) -> None:
        self._overrides[key] = value

    def get_scoped(self, scope: str, key: str, default: Any = None) -> Any:
        return self.get(f"{scope}.{key}", default)

    @staticmethod
    def _resolve_dot(data: dict[str, Any], dot_key: str) -> Any:
        current: Any = data
        for part in dot_key.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current
