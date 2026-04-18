"""
last30days research tool wrapper for TitanShift.

Wraps the `last30days` Python package (or module entrypoint) to perform
multi-source social intelligence research and emit a `document.markdown`
artifact with full provenance.

Requires `last30days` to be installed:
    pip install last30days

Config keys read from `skills.last30days` in harness.config.json:
    SCRAPECREATORS_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY, BRAVE_API_KEY,
    emit, save_dir
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.tools.definitions import ToolDefinition
from harness.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENV_KEY_MAP: dict[str, str] = {
    "SCRAPECREATORS_API_KEY": "SCRAPECREATORS_API_KEY",
    "XAI_API_KEY": "XAI_API_KEY",
    "OPENROUTER_API_KEY": "OPENROUTER_API_KEY",
    "BRAVE_API_KEY": "BRAVE_API_KEY",
}

_DEFAULT_TIMEOUT_S = 300
_MAX_TIMEOUT_S = 600
_MAX_STDERR_CHARS = 2000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_last30days_available() -> bool:
    """Return True if the last30days package is importable."""
    return importlib.util.find_spec("last30days") is not None


def _build_env(cfg_last30days: dict[str, Any]) -> dict[str, str]:
    """
    Build a minimal subprocess environment from config.

    Starts from a clean copy of the current process environment and adds
    only non-empty key values from the config namespace, never logging them.
    """
    env = dict(os.environ)
    for config_key, env_key in _ENV_KEY_MAP.items():
        value = str(cfg_last30days.get(config_key, "") or "").strip()
        if value:
            env[env_key] = value
    return env


def _artifact_id(topic: str) -> str:
    return hashlib.sha256(topic.encode()).hexdigest()[:12]


def _normalize_path(path: str) -> str:
    return str(Path(path).resolve()).replace("\\", "/")


def _clamp_timeout(value: int | None) -> int:
    if value is None:
        return _DEFAULT_TIMEOUT_S
    return min(max(1, int(value)), _MAX_TIMEOUT_S)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_last30days_tools(tools: ToolRegistry, cfg_skills: dict[str, Any] | None = None) -> None:
    """Register the last30days_research tool into the given ToolRegistry."""

    cfg_last30days: dict[str, Any] = (cfg_skills or {}).get("last30days", {})

    # ── last30days_research ──────────────────────────────────────────────

    async def last30days_research_handler(args: dict[str, Any]) -> dict[str, Any]:
        topic = str(args.get("topic") or "").strip()
        if not topic:
            raise ValueError("topic is required")

        if not _is_last30days_available():
            return {
                "ok": False,
                "error": (
                    "last30days package is not installed. "
                    "Install it with: pip install last30days"
                ),
                "install_hint": "pip install last30days",
            }

        # Resolve save_dir: args override > config > default
        raw_save_dir = str(args.get("save_dir") or cfg_last30days.get("save_dir") or "").strip()
        if raw_save_dir:
            save_dir = Path(raw_save_dir).resolve()
        else:
            save_dir = Path.cwd() / ".titantshift" / "last30days"
        save_dir.mkdir(parents=True, exist_ok=True)

        emit = str(args.get("emit") or cfg_last30days.get("emit") or "compact").strip()
        timeout_s = _clamp_timeout(args.get("timeout_s"))

        # Build subprocess command — no shell to prevent injection
        cmd = [sys.executable, "-m", "last30days", topic, "--emit", emit, "--out", str(save_dir)]
        max_sources = args.get("max_sources")
        if max_sources is not None:
            cmd.extend(["--max-sources", str(int(max_sources))])

        env = _build_env(cfg_last30days)
        generated_at = datetime.now(timezone.utc).isoformat()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"last30days timed out after {timeout_s}s for topic: {topic!r}",
                "topic": topic,
            }

        if result.returncode != 0:
            stderr_excerpt = (result.stderr or "").strip()[-_MAX_STDERR_CHARS:]
            return {
                "ok": False,
                "error": f"last30days exited with code {result.returncode}",
                "stderr": stderr_excerpt,
                "topic": topic,
            }

        # Locate the produced Markdown file — last30days writes <slug>.md by default
        candidates = sorted(save_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return {
                "ok": False,
                "error": "last30days completed but no Markdown output was found",
                "topic": topic,
                "save_dir": str(save_dir),
            }

        report_path = candidates[0]
        existed_before = len(candidates) > 1

        normalized = _normalize_path(str(report_path))
        content_preview = report_path.read_text(encoding="utf-8", errors="replace")[:500]

        # Best-effort source count from stdout
        source_count: int | None = None
        for line in (result.stdout or "").splitlines():
            if "source" in line.lower() and any(c.isdigit() for c in line):
                import re
                m = re.search(r"\d+", line)
                if m:
                    source_count = int(m.group())
                    break

        provenance: dict[str, Any] = {
            "generated_at": generated_at,
            "topic": topic,
            "emit": emit,
            "generator": "last30days_research",
        }
        if source_count is not None:
            provenance["source_count"] = source_count

        artifact = {
            "id": _artifact_id(normalized),
            "kind": "document.markdown",
            "mime_type": "text/markdown",
            "path": normalized,
            "title": f"Research: {topic}",
            "generator": "last30days_research",
            "backend": "last30days_backend",
            "verified": True,
            "provenance": provenance,
            "preview": content_preview,
        }

        path_key = "updated_paths" if existed_before else "created_paths"

        return {
            "ok": True,
            "topic": topic,
            "summary": f"Research brief generated for: {topic}",
            "report_path": normalized,
            path_key: [normalized],
            "artifacts": [artifact],
        }

    tools.register_tool(ToolDefinition(
        name="last30days_research",
        description=(
            "Run multi-source social intelligence research (Reddit, X, YouTube, "
            "Hacker News, Polymarket, GitHub, web) for a given topic and emit a "
            "structured Markdown brief artifact."
        ),
        needs_network=True,
        required_commands=[],
        handler=last30days_research_handler,
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Research topic or question (required).",
                },
                "save_dir": {
                    "type": "string",
                    "description": "Output directory override. Defaults to .titantshift/last30days/.",
                },
                "emit": {
                    "type": "string",
                    "enum": ["compact", "full"],
                    "description": "Output verbosity. Defaults to config value (compact).",
                },
                "max_sources": {
                    "type": "integer",
                    "description": "Cap the number of sources searched.",
                },
                "timeout_s": {
                    "type": "integer",
                    "description": f"Max runtime in seconds (1–{_MAX_TIMEOUT_S}). Default {_DEFAULT_TIMEOUT_S}.",
                },
            },
            "required": ["topic"],
        },
    ))
