from __future__ import annotations

import re
import shlex
from typing import Any

import httpx

from harness.execution.runner import ExecutionDeniedError, ExecutionModule
from harness.tools.definitions import ToolDefinition
from harness.tools.registry import ToolRegistry


def register_builtin_tools(tools: ToolRegistry, execution: ExecutionModule) -> None:
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
            description="Run shell commands through policy-constrained execution module",
            handler=shell_command_handler,
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
            description="Fetch webpage text content over HTTP for summarization/research",
            needs_network=True,
            handler=web_fetch_handler,
        )
    )
