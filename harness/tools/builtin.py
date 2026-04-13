from __future__ import annotations

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
