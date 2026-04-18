"""
Unit tests for the last30days_research tool wrapper.

Tests use subprocess mocking — no network or last30days package required.
Covers the 5 cases from the spec test plan plus registration and schema checks.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.runtime.bootstrap import build_runtime
from harness.tools.last30days import (
    _build_env,
    _clamp_timeout,
    _is_last30days_available,
    register_last30days_tools,
)
from harness.tools.registry import PermissionPolicy, ToolRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_registry() -> ToolRegistry:
    """A ToolRegistry with no policy restrictions for handler testing."""
    policy = PermissionPolicy(
        deny_all_by_default=False,
        allow_network=True,
        allowed_paths=[],
        allowed_tool_names=set(),
        blocked_tool_names=set(),
        allowed_command_prefixes=[],
    )
    reg = ToolRegistry(policy)
    register_last30days_tools(reg, cfg_skills={"last30days": {}})
    return reg


def _call(handler, args: dict) -> dict:
    return asyncio.run(handler(args))


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------

def test_last30days_research_registered_in_runtime() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("last30days_research")
    assert tool is not None
    assert tool.name == "last30days_research"
    assert tool.needs_network is True


def test_last30days_research_schema() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("last30days_research")
    assert tool is not None
    schema = tool.parameters
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    assert "topic" in schema.get("required", [])
    props = schema.get("properties", {})
    assert "topic" in props
    assert "emit" in props
    assert "save_dir" in props
    assert "max_sources" in props
    assert "timeout_s" in props


# ---------------------------------------------------------------------------
# 2. Missing dependency produces actionable install error
# ---------------------------------------------------------------------------

def test_missing_last30days_package_returns_install_hint(isolated_registry, tmp_path) -> None:
    handler = isolated_registry.get_tool("last30days_research").handler
    with patch("harness.tools.last30days._is_last30days_available", return_value=False):
        result = _call(handler, {"topic": "AI funding 2025", "save_dir": str(tmp_path)})
    assert result["ok"] is False
    assert "install" in result.get("error", "").lower()
    assert "install_hint" in result


# ---------------------------------------------------------------------------
# 3. Successful run writes artifact and returns deterministic payload
# ---------------------------------------------------------------------------

def test_successful_run_emits_markdown_artifact(isolated_registry, tmp_path) -> None:
    report = tmp_path / "ai_funding_2025.md"
    report.write_text("# AI Funding Research\n\nContent here.", encoding="utf-8")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Found 12 sources"
    mock_result.stderr = ""

    handler = isolated_registry.get_tool("last30days_research").handler
    with patch("harness.tools.last30days._is_last30days_available", return_value=True), \
         patch("subprocess.run", return_value=mock_result):
        result = _call(handler, {"topic": "AI funding 2025", "save_dir": str(tmp_path)})

    assert result["ok"] is True
    assert result["topic"] == "AI funding 2025"
    assert "report_path" in result
    artifacts = result.get("artifacts", [])
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art["kind"] == "document.markdown"
    assert art["mime_type"] == "text/markdown"
    assert art["verified"] is True
    assert art["provenance"]["topic"] == "AI funding 2025"
    assert art["provenance"]["generator"] == "last30days_research"
    assert art["provenance"]["source_count"] == 12


# ---------------------------------------------------------------------------
# 4. Timeout path produces bounded error
# ---------------------------------------------------------------------------

def test_timeout_returns_bounded_error(isolated_registry, tmp_path) -> None:
    handler = isolated_registry.get_tool("last30days_research").handler
    with patch("harness.tools.last30days._is_last30days_available", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=5)):
        result = _call(handler, {"topic": "test topic", "save_dir": str(tmp_path), "timeout_s": 5})
    assert result["ok"] is False
    assert "timed out" in result["error"].lower()
    assert result["topic"] == "test topic"


# ---------------------------------------------------------------------------
# 5. Config key injection passes only non-empty values
# ---------------------------------------------------------------------------

def test_build_env_injects_only_non_empty_keys() -> None:
    # Isolate from real environment so blank values are deterministic
    with patch.dict(os.environ, {}, clear=True):
        cfg = {
            "SCRAPECREATORS_API_KEY": "key123",
            "XAI_API_KEY": "",            # empty — must NOT be injected
            "OPENROUTER_API_KEY": "  ",   # whitespace — must NOT be injected
            "BRAVE_API_KEY": "brave456",
        }
        env = _build_env(cfg)
    assert env["SCRAPECREATORS_API_KEY"] == "key123"
    assert env["BRAVE_API_KEY"] == "brave456"
    assert env.get("XAI_API_KEY", "") == ""
    assert env.get("OPENROUTER_API_KEY", "").strip() == ""


def test_build_env_does_not_log_secrets(capsys) -> None:
    cfg = {"SCRAPECREATORS_API_KEY": "supersecret"}
    _build_env(cfg)
    captured = capsys.readouterr()
    assert "supersecret" not in captured.out
    assert "supersecret" not in captured.err


# ---------------------------------------------------------------------------
# 6. Existing report path updates updated_paths (not created_paths)
# ---------------------------------------------------------------------------

def test_existing_report_uses_updated_paths(isolated_registry, tmp_path) -> None:
    # Pre-create two .md files so the "existed_before" branch triggers
    old_report = tmp_path / "old_research.md"
    new_report = tmp_path / "new_research.md"
    old_report.write_text("# Old", encoding="utf-8")
    import time; time.sleep(0.01)
    new_report.write_text("# New content", encoding="utf-8")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    handler = isolated_registry.get_tool("last30days_research").handler
    with patch("harness.tools.last30days._is_last30days_available", return_value=True), \
         patch("subprocess.run", return_value=mock_result):
        result = _call(handler, {"topic": "existing topic", "save_dir": str(tmp_path)})

    assert result["ok"] is True
    assert "updated_paths" in result
    assert "created_paths" not in result


# ---------------------------------------------------------------------------
# 7. Non-zero exit code returns deterministic error
# ---------------------------------------------------------------------------

def test_nonzero_exit_returns_stderr_excerpt(isolated_registry, tmp_path) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "ModuleNotFoundError: No module named 'requests'"

    handler = isolated_registry.get_tool("last30days_research").handler
    with patch("harness.tools.last30days._is_last30days_available", return_value=True), \
         patch("subprocess.run", return_value=mock_result):
        result = _call(handler, {"topic": "broken topic", "save_dir": str(tmp_path)})

    assert result["ok"] is False
    assert "1" in result["error"]
    assert "requests" in result.get("stderr", "")


# ---------------------------------------------------------------------------
# 8. Timeout clamping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, 300),
    (0, 1),
    (-5, 1),
    (100, 100),
    (700, 600),   # capped at MAX_TIMEOUT_S
])
def test_clamp_timeout(raw, expected) -> None:
    assert _clamp_timeout(raw) == expected
