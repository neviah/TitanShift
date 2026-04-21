from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class ConfigManager:
    """Merges default config, file config, env vars, and runtime overrides."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self._base_config_path = workspace_root / "harness.config.json"
        self._local_config_path = workspace_root / "harness.config.local.json"
        defaults_file = workspace_root / "harness" / "config_defaults.json"
        if not defaults_file.exists():
            # Fallback for installed package usage outside the source checkout.
            defaults_file = Path(__file__).resolve().parents[1] / "config_defaults.json"
        self._defaults = self._load_json(defaults_file)
        self._base_config = self._load_json(self._base_config_path)
        local_config = self._load_json(self._local_config_path)
        # Local config overlays base so user-specific overrides never need to touch tracked config.
        self._file_config = self._deep_merge(self._base_config, local_config)
        self._overrides: dict[str, Any] = {}

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = f.read().strip()
            if not data:
                return {}
            loaded = json.loads(data)
            return loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, OSError):
            # Be resilient to transient partial writes and malformed local config.
            return {}

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
        local_config = self._load_json(self._local_config_path)

        if self._should_persist_to_local(key):
            # Secrets and per-user model choices belong in gitignored local config.
            self._delete_dot(self._base_config, key)
            self._set_dot(local_config, key, value)
            self._save_json(self._local_config_path, local_config)
        else:
            self._set_dot(self._base_config, key, value)

        self._file_config = self._deep_merge(self._base_config, local_config)
        self._save_json(self._base_config_path, self._base_config)

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

    @staticmethod
    def _delete_dot(data: dict[str, Any], dot_key: str) -> None:
        parts = dot_key.split('.')
        current: Any = data
        parents: list[tuple[dict[str, Any], str]] = []

        for part in parts[:-1]:
            if not isinstance(current, dict) or part not in current or not isinstance(current[part], dict):
                return
            parents.append((current, part))
            current = current[part]

        if not isinstance(current, dict) or parts[-1] not in current:
            return
        del current[parts[-1]]

        for parent, key in reversed(parents):
            child = parent.get(key)
            if isinstance(child, dict) and not child:
                del parent[key]
            else:
                break

    @staticmethod
    def _should_persist_to_local(key: str) -> bool:
        return key.startswith("model.") or key.endswith(".api_key")

    @staticmethod
    def _save_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
