from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
from typing import Any

import httpx

from harness.execution.runner import ExecutionDeniedError, ExecutionModule
from harness.tools.definitions import ToolDefinition
from harness.tools.registry import ToolRegistry


def register_builtin_tools(tools: ToolRegistry, execution: ExecutionModule) -> None:
    def _resolve_workspace_path(raw_path: str) -> Path:
        candidate = Path(raw_path)
        return candidate.resolve() if candidate.is_absolute() else (execution.default_cwd / candidate).resolve()

    async def shell_command_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw = str(args.get("command", "")).strip()
        if not raw:
            raise ValueError("command is required")

        parts = shlex.split(raw, posix=False)
        command = parts[0]
        command_args = [str(p) for p in parts[1:]]
        try:
            result = await execution.run_command(command, *command_args, cwd=args.get("cwd"))
        except ExecutionDeniedError as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
        }

    tools.register_tool(
        ToolDefinition(
            name="shell_command",
            description="Run a shell command through the policy-constrained execution module.",
            handler=shell_command_handler,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"},
                    "cwd": {"type": "string", "description": "Optional working directory"},
                },
                "required": ["command"],
            },
        )
    )

    async def create_directory_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("directory_path") or args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("directory_path is required")
        target = _resolve_workspace_path(raw_path)
        target.mkdir(parents=True, exist_ok=True)
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "created": True,
        }

    tools.register_tool(
        ToolDefinition(
            name="create_directory",
            description="Create a directory inside the allowed workspace. Use this before writing multiple related files or scaffolding a small app.",
            handler=create_directory_handler,
            parameters={
                "type": "object",
                "properties": {
                    "directory_path": {"type": "string", "description": "Directory path relative to workspace root or absolute allowed path"},
                },
                "required": ["directory_path"],
            },
        )
    )

    async def write_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("target_path is required")
        content = str(args.get("content", ""))
        overwrite = bool(args.get("overwrite", True))
        target = _resolve_workspace_path(raw_path)
        existed_before = target.exists()
        if target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")
        if target.exists() and not overwrite:
            raise ValueError(f"target_path already exists and overwrite=false: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "bytes_written": len(content.encode("utf-8")),
            "overwrote": existed_before,
        }

    tools.register_tool(
        ToolDefinition(
            name="write_file",
            description="Write or overwrite a UTF-8 text file inside the allowed workspace. Use this to create app files like HTML, CSS, JS, JSON, or config files.",
            handler=write_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "content": {"type": "string", "description": "Full file contents to write"},
                    "overwrite": {"type": "boolean", "description": "Whether existing files may be replaced; defaults to true"},
                },
                "required": ["target_path", "content"],
            },
        )
    )

    async def append_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("target_path is required")
        content = str(args.get("content", ""))
        ensure_newline = bool(args.get("ensure_newline", True))
        target = _resolve_workspace_path(raw_path)
        if target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        existed_before = target.exists()
        prefix = ""
        if existed_before and ensure_newline:
            try:
                existing = target.read_text(encoding="utf-8", errors="replace")
            except Exception:
                existing = ""
            if existing and not existing.endswith("\n") and content and not content.startswith("\n"):
                prefix = "\n"

        to_write = f"{prefix}{content}"
        with target.open("a", encoding="utf-8") as f:
            f.write(to_write)

        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "bytes_written": len(to_write.encode("utf-8")),
            "appended": True,
            "created": not existed_before,
        }

    tools.register_tool(
        ToolDefinition(
            name="append_file",
            description="Append UTF-8 text to an existing file or create it if missing. Prefer this when user asks to keep existing content and add a new line.",
            handler=append_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "content": {"type": "string", "description": "Text to append"},
                    "ensure_newline": {"type": "boolean", "description": "Insert a newline before appended content when needed; defaults to true"},
                },
                "required": ["target_path", "content"],
            },
        )
    )

    async def replace_in_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        old_text = str(args.get("old_text", ""))
        new_text = str(args.get("new_text", ""))
        if not raw_path:
            raise ValueError("target_path is required")
        if not old_text:
            raise ValueError("old_text is required")

        count = int(args.get("count", 1))
        target = _resolve_workspace_path(raw_path)
        if not target.exists() or not target.is_file():
            raise ValueError(f"file not found: {target}")

        content = target.read_text(encoding="utf-8", errors="replace")
        replaced = content.replace(old_text, new_text, count if count > 0 else -1)
        occurrences = content.count(old_text)
        applied = min(occurrences, count) if count > 0 else occurrences
        if applied == 0:
            raise ValueError("old_text not found in target file")
        target.write_text(replaced, encoding="utf-8")

        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "replacements": applied,
            "bytes_written": len(replaced.encode("utf-8")),
        }

    tools.register_tool(
        ToolDefinition(
            name="replace_in_file",
            description="Replace text in an existing UTF-8 file. Use for targeted edits without rewriting whole files.",
            handler=replace_in_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "old_text": {"type": "string", "description": "Existing text to replace"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                    "count": {"type": "integer", "description": "Maximum replacements; defaults to 1"},
                },
                "required": ["target_path", "old_text", "new_text"],
            },
        )
    )

    async def json_edit_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        updates = args.get("updates")
        if not raw_path:
            raise ValueError("target_path is required")
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty object")

        target = _resolve_workspace_path(raw_path)
        document: dict[str, Any] = {}
        if target.exists() and target.is_file():
            raw = target.read_text(encoding="utf-8", errors="replace").strip()
            if raw:
                loaded = json.loads(raw)
                if not isinstance(loaded, dict):
                    raise ValueError("target JSON must be an object")
                document = loaded
        elif target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")

        for raw_key, value in updates.items():
            key_path = str(raw_key).strip()
            if not key_path:
                continue
            parts = [p for p in key_path.split(".") if p]
            cursor: dict[str, Any] = document
            for part in parts[:-1]:
                nxt = cursor.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cursor[part] = nxt
                cursor = nxt
            cursor[parts[-1]] = value

        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(document, indent=2, sort_keys=True)
        target.write_text(serialized + "\n", encoding="utf-8")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "updated_keys": sorted(str(k) for k in updates.keys()),
            "bytes_written": len((serialized + "\n").encode("utf-8")),
        }

    tools.register_tool(
        ToolDefinition(
            name="json_edit",
            description="Upsert keys in a JSON object file using dot-path keys (for example: scripts.build).",
            handler=json_edit_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "JSON file path relative to workspace root or absolute allowed path"},
                    "updates": {
                        "type": "object",
                        "description": "Map of dot-path keys to values (e.g. {'scripts.build':'vite build'})",
                    },
                },
                "required": ["target_path", "updates"],
            },
        )
    )

    async def read_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or args.get("target_path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")
        target = _resolve_workspace_path(raw_path)
        if not target.exists() or not target.is_file():
            raise ValueError(f"file not found: {target}")
        max_chars = int(args.get("max_chars", 12000))
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    tools.register_tool(
        ToolDefinition(
            name="read_file",
            description="Read a text file from the allowed workspace. Use this before edits to inspect existing content.",
            handler=read_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "max_chars": {"type": "integer", "description": "Max characters to return (default 12000)"},
                },
                "required": ["path"],
            },
        )
    )

    async def list_directory_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or args.get("directory_path") or ".").strip()
        target = _resolve_workspace_path(raw_path)
        if not target.exists() or not target.is_dir():
            raise ValueError(f"directory not found: {target}")
        max_entries = max(1, min(int(args.get("max_entries", 200)), 1000))
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        rows: list[dict[str, Any]] = []
        for item in entries[:max_entries]:
            rows.append(
                {
                    "name": item.name,
                    "path": str(item).replace("\\", "/"),
                    "is_dir": item.is_dir(),
                }
            )
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "entries": rows,
            "truncated": len(entries) > max_entries,
        }

    tools.register_tool(
        ToolDefinition(
            name="list_directory",
            description="List files and folders under a workspace directory.",
            handler=list_directory_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to workspace root (default .)"},
                    "max_entries": {"type": "integer", "description": "Maximum entries returned (default 200)"},
                },
            },
        )
    )

    async def rename_or_move_handler(args: dict[str, Any]) -> dict[str, Any]:
        source_raw = str(args.get("source_path") or "").strip()
        destination_raw = str(args.get("destination_path") or "").strip()
        if not source_raw or not destination_raw:
            raise ValueError("source_path and destination_path are required")
        source = _resolve_workspace_path(source_raw)
        destination = _resolve_workspace_path(destination_raw)
        if not source.exists():
            raise ValueError(f"source_path not found: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        return {
            "ok": True,
            "source_path": str(source).replace("\\", "/"),
            "destination_path": str(destination).replace("\\", "/"),
        }

    tools.register_tool(
        ToolDefinition(
            name="rename_or_move",
            description="Rename or move a file/directory inside the workspace.",
            handler=rename_or_move_handler,
            parameters={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                },
                "required": ["source_path", "destination_path"],
            },
        )
    )

    async def delete_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or args.get("target_path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")
        if str(args.get("confirm", "")).strip() != "I_UNDERSTAND_DELETE":
            raise PermissionError("delete_file requires confirm='I_UNDERSTAND_DELETE'")
        target = _resolve_workspace_path(raw_path)
        if not target.exists():
            return {"ok": True, "path": str(target).replace("\\", "/"), "deleted": False}
        if target.is_dir():
            for root, dirs, files in os.walk(target, topdown=False):
                for f in files:
                    Path(root, f).unlink(missing_ok=True)
                for d in dirs:
                    Path(root, d).rmdir()
            target.rmdir()
        else:
            target.unlink(missing_ok=True)
        return {"ok": True, "path": str(target).replace("\\", "/"), "deleted": True}

    tools.register_tool(
        ToolDefinition(
            name="delete_file",
            description="Delete a file or directory inside the workspace. Requires explicit confirmation token.",
            handler=delete_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "confirm": {"type": "string", "description": "Must be exactly I_UNDERSTAND_DELETE"},
                },
                "required": ["path", "confirm"],
            },
        )
    )

    async def search_workspace_handler(args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip().lower()
        if not query:
            raise ValueError("query is required")
        max_results = max(1, min(int(args.get("max_results", 50)), 500))
        rows: list[dict[str, Any]] = []
        for root, _, files in os.walk(execution.default_cwd):
            for file_name in files:
                full = Path(root) / file_name
                rel = str(full.relative_to(execution.default_cwd)).replace("\\", "/")
                matched = query in rel.lower()
                if not matched:
                    try:
                        text = full.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    idx = text.lower().find(query)
                    if idx >= 0:
                        snippet_start = max(0, idx - 80)
                        snippet_end = min(len(text), idx + 120)
                        rows.append({"path": rel, "snippet": text[snippet_start:snippet_end]})
                else:
                    rows.append({"path": rel, "snippet": ""})
                if len(rows) >= max_results:
                    return {"ok": True, "query": query, "results": rows, "truncated": True}
        return {"ok": True, "query": query, "results": rows, "truncated": False}

    tools.register_tool(
        ToolDefinition(
            name="search_workspace",
            description="Search workspace paths and file contents for a query string.",
            handler=search_workspace_handler,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "Maximum matches to return"},
                },
                "required": ["query"],
            },
        )
    )

    async def run_project_check_handler(args: dict[str, Any]) -> dict[str, Any]:
        check = str(args.get("check") or "").strip().lower()
        cwd = args.get("cwd")
        mapping: dict[str, tuple[str, list[str]]] = {
            "python_tests": ("python", ["-m", "pytest", "-q"]),
            "npm_test": ("npm", ["test"]),
            "npm_build": ("npm", ["run", "build"]),
            "python_check": ("python", ["-m", "pytest", "-q"]),
        }
        if check not in mapping:
            raise ValueError("check must be one of: python_tests, python_check, npm_test, npm_build")
        command, command_args = mapping[check]
        try:
            result = await execution.run_command(command, *command_args, cwd=cwd)
        except ExecutionDeniedError as exc:
            return {"ok": False, "error": str(exc), "check": check}
        return {
            "ok": result.returncode == 0,
            "check": check,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
        }

    tools.register_tool(
        ToolDefinition(
            name="run_project_check",
            description="Run approved project checks like pytest and npm build via a constrained wrapper.",
            handler=run_project_check_handler,
            parameters={
                "type": "object",
                "properties": {
                    "check": {"type": "string", "description": "python_tests | python_check | npm_test | npm_build"},
                    "cwd": {"type": "string", "description": "Optional working directory"},
                },
                "required": ["check"],
            },
        )
    )

    async def web_fetch_handler(args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url", "")).strip()
        if not url:
            raise ValueError("url is required")

        timeout_s = float(args.get("timeout_s", 10.0))
        max_chars = int(args.get("max_chars", 8000))

        verify = bool(args.get("verify_tls", True))
        try:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True, verify=verify) as client:
                response = await client.get(url)
                response.raise_for_status()
                body = response.text
        except Exception as exc:
            # Common local Windows cert-chain issue; retry with TLS verify disabled.
            msg = str(exc).lower()
            if "certificate verify failed" not in msg:
                raise
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True, verify=False) as client:
                response = await client.get(url)
                response.raise_for_status()
                body = response.text

        # Minimal HTML cleanup into readable plain text.
        body = re.sub(r"(?is)<script.*?>.*?</script>", " ", body)
        body = re.sub(r"(?is)<style.*?>.*?</style>", " ", body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()

        return {
            "ok": True,
            "url": str(response.url),
            "status_code": response.status_code,
            "content": body[:max_chars],
            "truncated": len(body) > max_chars,
        }

    tools.register_tool(
        ToolDefinition(
            name="web_fetch",
            description="Fetch the plain-text content of a URL for summarisation or research. Use this whenever the user asks about live data, current events, websites, news, prices, or anything requiring information from the web.",
            needs_network=True,
            handler=web_fetch_handler,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch (must start with http:// or https://)"},
                    "max_chars": {"type": "integer", "description": "Maximum characters to return (default 8000)"},
                },
                "required": ["url"],
            },
        )
    )
