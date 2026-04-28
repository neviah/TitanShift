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


def _collect_tool_names(raw: str) -> list[str]:
    tools: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            for key in ("tool", "tool_name", "name"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    tools.append(value.strip())
    # Preserve order while deduplicating.
    seen: set[str] = set()
    out: list[str] = []
    for item in tools:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_response(raw: str) -> str:
    last_text = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            for key in ("result", "text", "message", "content", "response", "output", "summary"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    last_text = value.strip()
    if last_text:
        return last_text
    return raw.strip()[-8000:]


def _stream_has_error(raw: str) -> str | None:
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type", "")).strip().lower()
        if event_type == "error":
            error_obj = payload.get("error")
            if isinstance(error_obj, dict):
                data = error_obj.get("data")
                if isinstance(data, dict):
                    message = data.get("message")
                    if isinstance(message, str) and message.strip():
                        return message.strip()
            return "opencode returned an error event"
    return None


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
    model = _safe_text(os.getenv("OPENAI_MODEL"))
    base_url = _safe_text(os.getenv("OPENAI_BASE_URL"))

    model_for_cli = model
    if model and "openrouter.ai" in base_url.lower() and not model.lower().startswith("openrouter/"):
        # OpenCode expects provider/model format; OpenRouter model ids are usually bare slugs.
        model_for_cli = f"openrouter/{model}"

    def _run_once(selected_model: str | None) -> subprocess.CompletedProcess[str]:
        cmd = [
            opencode_bin,
            "run",
            prompt,
            "--format",
            "json",
            "--dir",
            workspace_root,
            "--dangerously-skip-permissions",
        ]
        if selected_model:
            cmd.extend(["--model", selected_model])
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=workspace_root,
        )

    opencode_bin = shutil.which("opencode") or shutil.which("opencode.cmd") or "opencode.cmd"
    proc = _run_once(model_for_cli or None)

    stdout_text = proc.stdout or ""
    stderr_text = proc.stderr or ""
    success = proc.returncode == 0
    stream_error = _stream_has_error(stdout_text)
    if stream_error and "model not found" in stream_error.lower():
        # Retry once without forcing model; OpenCode can use provider defaults.
        proc = _run_once(None)
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""
        success = proc.returncode == 0
        stream_error = _stream_has_error(stdout_text)
    if stream_error:
        success = False

    result = {
        "success": success,
        "engine": "opencode",
        "model": "opencode",
        "provider_model": model or None,
        "response": _extract_response(stdout_text),
        "used_tools": _collect_tool_names(stdout_text),
        "created_paths": [],
        "updated_paths": [],
        "artifacts": [],
        "error": None if success else (stream_error or _safe_text(stderr_text) or f"opencode exited with code {proc.returncode}"),
        "stderr": stderr_text[-8000:],
        "raw_output": stdout_text[-16000:],
    }

    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
