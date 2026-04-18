"""
Smoke tests for OfficeCLI tool wrappers.

These tests verify that:
1. All OfficeCLI tools are registered in the runtime tool registry.
2. Tools fail gracefully when officecli binary is unavailable.
3. Tool parameter schemas are well-formed.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from harness.runtime.bootstrap import build_runtime
from harness.tools.officecli import _officecli_binary


# ── Registration tests ──────────────────────────────────────────────────────


def test_officecli_create_document_registered() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("officecli_create_document")
    assert tool is not None
    assert tool.name == "officecli_create_document"
    assert "officecli" in (tool.required_commands or [])


def test_officecli_add_element_registered() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("officecli_add_element")
    assert tool is not None
    assert tool.name == "officecli_add_element"


def test_officecli_view_document_registered() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("officecli_view_document")
    assert tool is not None
    assert tool.name == "officecli_view_document"


def test_officecli_set_properties_registered() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("officecli_set_properties")
    assert tool is not None
    assert tool.name == "officecli_set_properties"


def test_officecli_merge_template_registered() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("officecli_merge_template")
    assert tool is not None
    assert tool.name == "officecli_merge_template"


def test_officecli_batch_registered() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool = runtime.tools.get_tool("officecli_batch")
    assert tool is not None
    assert tool.name == "officecli_batch"


# ── Schema sanity ────────────────────────────────────────────────────────────


def test_officecli_tool_schemas_have_required_fields() -> None:
    runtime = build_runtime(Path(".").resolve())
    tool_names = [
        "officecli_create_document",
        "officecli_add_element",
        "officecli_view_document",
        "officecli_set_properties",
        "officecli_merge_template",
        "officecli_batch",
    ]
    for name in tool_names:
        tool = runtime.tools.get_tool(name)
        assert tool is not None, f"Tool {name} not found"
        schema = tool.parameters
        assert isinstance(schema, dict), f"{name}: parameters must be a dict"
        assert schema.get("type") == "object", f"{name}: parameters type must be 'object'"
        assert "properties" in schema, f"{name}: parameters must have 'properties'"
        assert "required" in schema, f"{name}: parameters must have 'required'"


# ── Graceful failure without binary ─────────────────────────────────────────


@pytest.mark.skipif(
    shutil.which("officecli") is not None,
    reason="officecli is installed; binary-missing error path not applicable",
)
def test_officecli_create_document_fails_without_binary() -> None:
    """When officecli binary is absent the tool raises RuntimeError, not a crash."""
    runtime = build_runtime(Path(".").resolve())
    with pytest.raises(RuntimeError, match="officecli binary not found"):
        asyncio.run(
            runtime.tools.execute_tool(
                "officecli_create_document",
                {"path": "tmp/test_missing_binary.docx"},
            )
        )


@pytest.mark.skipif(
    shutil.which("officecli") is not None,
    reason="officecli is installed; binary-missing error path not applicable",
)
def test_officecli_view_document_fails_without_binary() -> None:
    runtime = build_runtime(Path(".").resolve())
    with pytest.raises(RuntimeError, match="officecli binary not found"):
        asyncio.run(
            runtime.tools.execute_tool(
                "officecli_view_document",
                {"path": "some_document.docx"},
            )
        )


# ── Validation tests ────────────────────────────────────────────────────────


def test_officecli_create_document_rejects_unknown_extension() -> None:
    runtime = build_runtime(Path(".").resolve())
    with pytest.raises(ValueError, match=r"\.docx|\.xlsx|\.pptx"):
        asyncio.run(
            runtime.tools.execute_tool(
                "officecli_create_document",
                {"path": "output.txt"},
            )
        )


def test_officecli_set_properties_rejects_empty_props() -> None:
    runtime = build_runtime(Path(".").resolve())
    with pytest.raises(ValueError, match="props"):
        asyncio.run(
            runtime.tools.execute_tool(
                "officecli_set_properties",
                {"path": "output.docx", "props": {}},
            )
        )


def test_officecli_merge_template_rejects_empty_data() -> None:
    runtime = build_runtime(Path(".").resolve())
    with pytest.raises(ValueError, match="data"):
        asyncio.run(
            runtime.tools.execute_tool(
                "officecli_merge_template",
                {"path": "output.docx", "data": {}},
            )
        )


def test_officecli_batch_rejects_empty_operations() -> None:
    runtime = build_runtime(Path(".").resolve())
    with pytest.raises(ValueError, match="operations"):
        asyncio.run(
            runtime.tools.execute_tool(
                "officecli_batch",
                {"path": "output.docx", "operations": []},
            )
        )


# ── Binary detection helper ─────────────────────────────────────────────────


def test_officecli_binary_helper_returns_none_or_string() -> None:
    result = _officecli_binary()
    assert result is None or isinstance(result, str)
