from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_response(parsed: dict[str, Any], fallback: str) -> str:
    for key in ("result", "response", "text", "message", "content", "output"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    message_obj = parsed.get("message")
    if isinstance(message_obj, dict):
        for key in ("text", "content", "message"):
            nested = message_obj.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    messages = parsed.get("messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return fallback.strip()[-8000:]


def _collect_tool_names(parsed: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("used_tools", "tools", "tool_calls"):
        value = parsed.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str) and entry.strip():
                    names.append(entry.strip())
                elif isinstance(entry, dict):
                    tool_name = entry.get("name") or entry.get("tool")
                    if isinstance(tool_name, str) and tool_name.strip():
                        names.append(tool_name.strip())
    seen: set[str] = set()
    out: list[str] = []
    for item in names:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def main() -> int:
    raw_input = sys.stdin.read()
    try:
        payload = json.loads(raw_input) if raw_input.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    prompt = _safe_text(payload.get("prompt"))
    workspace_root = _safe_text(payload.get("workspace_root")) or str(Path.cwd())

    provider = _safe_text(os.getenv("OPENCLAUDE_PROVIDER"))
    model = _safe_text(os.getenv("OPENAI_MODEL") or os.getenv("OPENCLAUDE_MODEL"))

    openclaude_bin = shutil.which("openclaude") or shutil.which("openclaude.cmd") or "openclaude.cmd"

    cmd = [
        openclaude_bin,
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "bypassPermissions",
        "--dangerously-skip-permissions",
    ]
    if provider:
        cmd.extend(["--provider", provider])
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=workspace_root,
    )

    stdout_text = proc.stdout or ""
    stderr_text = proc.stderr or ""
    success = proc.returncode == 0

    parsed: dict[str, Any] = {}
    if stdout_text.strip():
        try:
            loaded = json.loads(stdout_text)
            if isinstance(loaded, dict):
                parsed = loaded
        except Exception:
            parsed = {}

    result = {
        "success": success,
        "engine": "openclaude",
        "model": "openclaude",
        "provider_model": model or None,
        "response": _extract_response(parsed, stdout_text),
        "used_tools": _collect_tool_names(parsed),
        "created_paths": [],
        "updated_paths": [],
        "artifacts": [],
        "error": None if success else (_safe_text(stderr_text) or f"openclaude exited with code {proc.returncode}"),
        "stderr": stderr_text[-8000:],
        "raw_output": stdout_text[-16000:],
    }

    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
