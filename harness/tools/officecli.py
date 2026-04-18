"""
OfficeCLI tool wrappers for TitanShift.

Requires the `officecli` binary to be installed and reachable on PATH.
Install: https://github.com/iOfficeAI/OfficeCLI

Each tool wraps subprocess calls to the binary with --json output,
parses the structured response, and emits an ArtifactRecord where applicable.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.tools.definitions import ToolDefinition
from harness.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _officecli_binary() -> str | None:
    """Return path to officecli binary or None if not found."""
    return shutil.which("officecli")


def _run_officecli(*args: str, input_data: str | None = None) -> dict[str, Any]:
    """
    Execute officecli and return the parsed JSON response.

    Raises RuntimeError if the binary is missing or the exit code is non-zero.
    """
    binary = _officecli_binary()
    if binary is None:
        raise RuntimeError(
            "officecli binary not found on PATH. "
            "Install from https://github.com/iOfficeAI/OfficeCLI"
        )

    cmd = [binary, *args]
    result = subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        text=True,
        timeout=120,
    )

    raw_stdout = result.stdout.strip()
    raw_stderr = result.stderr.strip()

    if result.returncode != 0:
        raise RuntimeError(
            f"officecli exited with code {result.returncode}. "
            f"stderr: {raw_stderr or '(empty)'}"
        )

    # officecli returns JSON when --json is passed; fall back to raw text
    if raw_stdout.startswith("{") or raw_stdout.startswith("["):
        try:
            return json.loads(raw_stdout)
        except json.JSONDecodeError:
            pass

    return {"raw": raw_stdout, "stderr": raw_stderr}


def _artifact_id(path: str) -> str:
    return hashlib.sha256(path.encode()).hexdigest()[:12]


def _normalize(path: str) -> str:
    return str(Path(path).resolve()).replace("\\", "/")


def _ext_to_mime(ext: str) -> tuple[str, str]:
    """Return (mime_type, kind) for a given file extension."""
    ext = ext.lstrip(".").lower()
    mapping = {
        "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document.docx"),
        "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document.xlsx"),
        "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "document.pptx"),
    }
    return mapping.get(ext, ("application/octet-stream", "document.office"))


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_officecli_tools(tools: ToolRegistry) -> None:
    """Register all OfficeCLI tool wrappers into the given ToolRegistry."""

    # ── officecli_create_document ─────────────────────────────────────────

    async def officecli_create_document_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("path is required (e.g. outputs/report.docx)")

        target = Path(raw_path)
        if not target.is_absolute():
            # Resolve relative to cwd; caller must ensure it's within allowed paths
            target = Path.cwd() / target
        target = target.resolve()

        ext = target.suffix.lower().lstrip(".")
        if ext not in {"docx", "xlsx", "pptx"}:
            raise ValueError("path must end in .docx, .xlsx, or .pptx")

        target.parent.mkdir(parents=True, exist_ok=True)
        existed_before = target.exists()

        _run_officecli("create", str(target))

        normalized = _normalize(str(target))
        mime_type, kind = _ext_to_mime(ext)
        artifact_id = _artifact_id(normalized)
        generated_at = datetime.now(timezone.utc).isoformat()

        artifact = {
            "artifact_id": artifact_id,
            "kind": kind,
            "path": normalized,
            "mime_type": mime_type,
            "title": target.name,
            "summary": f"Empty {ext.upper()} document created by officecli",
            "generator": "officecli_create_document",
            "backend": "officecli_backend",
            "verified": True,
            "provenance": {
                "generated_at": generated_at,
                "document_type": ext,
            },
            "preview": None,
        }

        return {
            "ok": True,
            "path": normalized,
            "document_type": ext,
            "created_paths": [] if existed_before else [normalized],
            "updated_paths": [normalized] if existed_before else [],
            "artifacts": [artifact],
        }

    tools.register_tool(
        ToolDefinition(
            name="officecli_create_document",
            description=(
                "Create a blank Office document (.docx, .xlsx, or .pptx) using officecli. "
                "Returns an artifact record for the created file."
            ),
            required_commands=["officecli"],
            handler=officecli_create_document_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Output file path including extension. "
                            "Extension determines type: .docx, .xlsx, or .pptx. "
                            "Example: outputs/report.docx"
                        ),
                    },
                },
                "required": ["path"],
            },
        )
    )

    # ── officecli_add_element ─────────────────────────────────────────────

    async def officecli_add_element_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")

        parent = str(args.get("parent") or "/").strip()
        element_type = str(args.get("type") or "").strip()
        if not element_type:
            raise ValueError("type is required (e.g. paragraph, slide, chart, table)")

        props: dict[str, Any] = args.get("props") or {}
        if not isinstance(props, dict):
            raise ValueError("props must be an object")

        after = str(args.get("after") or "").strip() or None
        before = str(args.get("before") or "").strip() or None

        cmd = ["add", raw_path, parent, "--type", element_type]
        for key, value in props.items():
            cmd += ["--prop", f"{key}={value}"]
        if after:
            cmd += ["--after", after]
        if before:
            cmd += ["--before", before]
        cmd.append("--json")

        response = _run_officecli(*cmd)

        return {
            "ok": True,
            "path": _normalize(raw_path),
            "parent": parent,
            "type": element_type,
            "props": props,
            "response": response,
        }

    tools.register_tool(
        ToolDefinition(
            name="officecli_add_element",
            description=(
                "Add an element to an existing Office document using officecli. "
                "Supports slide, paragraph, shape, chart, table, row, image, and more. "
                "Use props to set text, style, position, color, and other attributes."
            ),
            required_commands=["officecli"],
            handler=officecli_add_element_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .docx, .xlsx, or .pptx file",
                    },
                    "parent": {
                        "type": "string",
                        "description": (
                            "XPath-style parent element to add into. "
                            "Examples: / (root), /body, '/slide[1]', '/Sheet1'. "
                            "Defaults to / (root)."
                        ),
                    },
                    "type": {
                        "type": "string",
                        "description": (
                            "Element type to add. "
                            "docx: paragraph, run, table, row, cell, image, header, footer, chart, hyperlink, bookmark, comment. "
                            "pptx: slide, shape, picture, chart, table, row, connector, group. "
                            "xlsx: sheet, row, cell, chart, image, table, sparkline, pivottable."
                        ),
                    },
                    "props": {
                        "type": "object",
                        "description": (
                            "Key-value properties for the element. "
                            "Common props: text, style, bold, italic, fontSize, color, background, x, y, width, height, value."
                        ),
                    },
                    "after": {
                        "type": "string",
                        "description": "Insert after this element path or 'find:text' anchor.",
                    },
                    "before": {
                        "type": "string",
                        "description": "Insert before this element path or 'find:text' anchor.",
                    },
                },
                "required": ["path", "type"],
            },
        )
    )

    # ── officecli_view_document ───────────────────────────────────────────

    async def officecli_view_document_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")

        mode = str(args.get("mode") or "outline").strip().lower()
        valid_modes = {"outline", "stats", "text", "issues", "annotated"}
        if mode not in valid_modes:
            raise ValueError(f"mode must be one of: {', '.join(sorted(valid_modes))}")

        cmd = ["view", raw_path, mode, "--json"]

        max_lines = args.get("max_lines")
        if max_lines is not None:
            cmd += ["--max-lines", str(int(max_lines))]

        response = _run_officecli(*cmd)

        return {
            "ok": True,
            "path": _normalize(raw_path),
            "mode": mode,
            "result": response,
        }

    tools.register_tool(
        ToolDefinition(
            name="officecli_view_document",
            description=(
                "Inspect an Office document using officecli. "
                "Returns outline structure, statistics, plain text, formatting issues, or annotated text. "
                "Use 'issues' mode to find formatting/content/structure problems before delivery."
            ),
            required_commands=["officecli"],
            handler=officecli_view_document_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .docx, .xlsx, or .pptx file",
                    },
                    "mode": {
                        "type": "string",
                        "description": (
                            "View mode: "
                            "outline (document structure), "
                            "stats (page/word/shape counts), "
                            "text (plain text extraction), "
                            "issues (formatting/content/structure problems), "
                            "annotated (text with formatting annotations). "
                            "Defaults to outline."
                        ),
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Limit output lines. Recommended for large documents.",
                    },
                },
                "required": ["path"],
            },
        )
    )

    # ── officecli_set_properties ──────────────────────────────────────────

    async def officecli_set_properties_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")

        element_path = str(args.get("element_path") or "/").strip()
        props: dict[str, Any] = args.get("props") or {}
        if not isinstance(props, dict) or not props:
            raise ValueError("props must be a non-empty object")

        cmd = ["set", raw_path, element_path]
        for key, value in props.items():
            cmd += ["--prop", f"{key}={value}"]
        cmd.append("--json")

        response = _run_officecli(*cmd)

        return {
            "ok": True,
            "path": _normalize(raw_path),
            "element_path": element_path,
            "props": props,
            "response": response,
        }

    tools.register_tool(
        ToolDefinition(
            name="officecli_set_properties",
            description=(
                "Modify properties of an element in an Office document using officecli. "
                "Use element_path to target a specific node (e.g. '/body/p[1]', '/slide[1]/shape[2]'). "
                "Use '/' for document-level properties. "
                "Supports find= prop for targeting specific text within an element."
            ),
            required_commands=["officecli"],
            handler=officecli_set_properties_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .docx, .xlsx, or .pptx file",
                    },
                    "element_path": {
                        "type": "string",
                        "description": (
                            "XPath-style path to the target element. "
                            "Examples: '/' (document-level), '/body/p[1]' (first paragraph), "
                            "'/slide[1]/shape[@id=550950021]' (specific shape by stable ID), "
                            "'/Sheet1/A1' (Excel cell). "
                            "Always single-quote paths containing brackets."
                        ),
                    },
                    "props": {
                        "type": "object",
                        "description": (
                            "Properties to set as key-value pairs. "
                            "Common: bold, italic, fontSize, color, text, value, fill, find, replace."
                        ),
                    },
                },
                "required": ["path", "props"],
            },
        )
    )

    # ── officecli_merge_template ──────────────────────────────────────────

    async def officecli_merge_template_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")

        data: dict[str, Any] = args.get("data") or {}
        if not isinstance(data, dict) or not data:
            raise ValueError("data must be a non-empty object of placeholder -> value mappings")

        # Use officecli batch set with find/replace for each placeholder
        operations = [
            {"command": "set", "path": "/", "props": {"find": placeholder, "replace": str(value)}}
            for placeholder, value in data.items()
        ]
        batch_json = json.dumps(operations)

        cmd = ["batch", raw_path, "--commands", batch_json, "--json"]
        response = _run_officecli(*cmd)

        normalized = _normalize(raw_path)
        ext = Path(raw_path).suffix.lower().lstrip(".")
        mime_type, kind = _ext_to_mime(ext)
        artifact_id = _artifact_id(normalized)
        generated_at = datetime.now(timezone.utc).isoformat()

        artifact = {
            "artifact_id": artifact_id,
            "kind": kind,
            "path": normalized,
            "mime_type": mime_type,
            "title": Path(raw_path).name,
            "summary": f"Merged {len(data)} placeholder(s) into {Path(raw_path).name}",
            "generator": "officecli_merge_template",
            "backend": "officecli_backend",
            "verified": True,
            "provenance": {
                "generated_at": generated_at,
                "placeholder_count": len(data),
            },
            "preview": None,
        }

        return {
            "ok": True,
            "path": normalized,
            "placeholder_count": len(data),
            "response": response,
            "artifacts": [artifact],
        }

    tools.register_tool(
        ToolDefinition(
            name="officecli_merge_template",
            description=(
                "Merge JSON data into placeholder tokens inside an Office document. "
                "Performs whole-document find/replace for each key->value pair in data. "
                "Use for mail merge, report templating, and dynamic document population. "
                "Returns an artifact record for the modified file."
            ),
            required_commands=["officecli"],
            handler=officecli_merge_template_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .docx, .xlsx, or .pptx template file",
                    },
                    "data": {
                        "type": "object",
                        "description": (
                            "Object mapping placeholder strings to replacement values. "
                            "Example: {\"{{CLIENT_NAME}}\": \"Acme Corp\", \"{{DATE}}\": \"2026-04-18\"}"
                        ),
                    },
                },
                "required": ["path", "data"],
            },
        )
    )

    # ── officecli_batch ───────────────────────────────────────────────────

    async def officecli_batch_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")

        operations = args.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ValueError("operations must be a non-empty array")

        force = bool(args.get("force", False))
        batch_json = json.dumps(operations)

        cmd = ["batch", raw_path, "--commands", batch_json, "--json"]
        if force:
            cmd.insert(-1, "--force")

        response = _run_officecli(*cmd)

        return {
            "ok": True,
            "path": _normalize(raw_path),
            "operation_count": len(operations),
            "force": force,
            "response": response,
        }

    tools.register_tool(
        ToolDefinition(
            name="officecli_batch",
            description=(
                "Execute multiple officecli operations on a document in a single save cycle. "
                "More efficient than individual calls for bulk edits. "
                "Each operation is an object with 'command' (set/add/remove/get/move/swap), "
                "'path', optional 'parent', 'type', 'props', and positional fields."
            ),
            required_commands=["officecli"],
            handler=officecli_batch_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .docx, .xlsx, or .pptx file",
                    },
                    "operations": {
                        "type": "array",
                        "description": (
                            "Array of operation objects. Each has: "
                            "command (set|add|remove|get|move|swap|view|validate), "
                            "path (element path), "
                            "props (key-value properties for set/add), "
                            "parent/type (for add), "
                            "to/after/before/index (for add/move)."
                        ),
                        "items": {"type": "object"},
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Continue past errors instead of stopping on first failure. Defaults to false.",
                    },
                },
                "required": ["path", "operations"],
            },
        )
    )
