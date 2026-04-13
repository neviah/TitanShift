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
        self._base_config = self._load_json(workspace_root / "harness.config.json")
        local_config = self._load_json(workspace_root / "harness.config.local.json")
        # local config overlays base — local values win, base is still the only file written by set()
        self._file_config = self._deep_merge(self._base_config, local_config)
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

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep-merge override into base, returning a new dict.  Override values win."""
        result = dict(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def set(self, key: str, value: Any) -> None:
        self._overrides[key] = value
        # Persist only to the base config file; local overrides are never clobbered.
        self._set_dot(self._base_config, key, value)
        local_config = self._load_json(self.workspace_root / "harness.config.local.json")
        self._file_config = self._deep_merge(self._base_config, local_config)
        self._save_file_config()

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

    @staticmethod
    def _set_dot(data: dict[str, Any], dot_key: str, value: Any) -> None:
        parts = dot_key.split('.')
        current = data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def _save_file_config(self) -> None:
        # Always write only the base config; harness.config.local.json is user-managed.
        path = self.workspace_root / 'harness.config.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8') as f:
            json.dump(self._base_config, f, indent=2)
            f.write('\n')
