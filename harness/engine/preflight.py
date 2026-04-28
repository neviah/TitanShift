from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from harness.runtime.config import ConfigManager


def normalize_command(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()]
    if isinstance(raw, str) and raw.strip():
        return [part for part in shlex.split(raw) if part.strip()]
    return []


def resolve_binary(binary: str) -> str | None:
    return shutil.which(binary) or shutil.which(f"{binary}.cmd")


def read_version(binary_path: str | None) -> str | None:
    if not binary_path:
        return None
    try:
        proc = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception:
        return None

    output = (proc.stdout or proc.stderr or "").strip()
    if not output:
        return None
    return output.splitlines()[0][:200]


def command_probe(config: ConfigManager, mode: str) -> dict[str, Any]:
    command = normalize_command(config.get(f"engine.sidecar.{mode}.command", []))
    if not command:
        return {
            "configured": False,
            "command": [],
            "binary": None,
            "binary_found": False,
            "binary_path": None,
            "binary_version": None,
            "wrapper_exists": False,
            "wrapper_path": None,
        }

    binary = command[0]
    binary_path = resolve_binary(binary)
    wrapper_path: Path | None = None
    wrapper_exists = True
    if len(command) > 1 and command[1].endswith(".py"):
        wrapper_path = Path(command[1])
        if not wrapper_path.is_absolute():
            wrapper_path = config.workspace_root / wrapper_path
        wrapper_exists = wrapper_path.exists()

    return {
        "configured": True,
        "command": command,
        "binary": binary,
        "binary_found": bool(binary_path),
        "binary_path": binary_path,
        "binary_version": read_version(binary_path),
        "wrapper_exists": wrapper_exists,
        "wrapper_path": str(wrapper_path) if wrapper_path is not None else None,
    }


def auth_probe(config: ConfigManager) -> dict[str, bool]:
    return {
        "has_api_key": bool(str(config.get("model.openai_compatible.api_key", "") or "").strip()),
        "has_base_url": bool(str(config.get("model.openai_compatible.base_url", "") or "").strip()),
        "has_model": bool(str(config.get("model.openai_compatible.model", "") or "").strip()),
    }


def engines_health_payload(config: ConfigManager) -> dict[str, Any]:
    lightning = command_probe(config, "lightning")
    superpowered = command_probe(config, "superpowered")
    return {
        "ok": True,
        "engine_use_sidecar": bool(config.get("engine.use_sidecar", False)),
        "disable_legacy_skills": bool(config.get("engine.disable_legacy_skills", False)),
        "lightning": lightning,
        "superpowered": superpowered,
        "auth_config": auth_probe(config),
    }
