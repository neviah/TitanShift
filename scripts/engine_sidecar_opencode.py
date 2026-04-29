from __future__ import annotations

import json
import os
import re
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
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            for key in ("response", "result", "text", "message", "content", "output", "summary"):
                value = loaded.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    except Exception:
        pass

    chunks: list[str] = []
    last_text = ""
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

        # opencode stream messages are often nested in a `part` envelope.
        part = payload.get("part")
        if isinstance(part, dict):
            part_text = part.get("text")
            if isinstance(part_text, str) and part_text.strip():
                text = part_text.strip()
                chunks.append(text)
                last_text = text

        # Some events return text directly at top level.
        for key in ("result", "text", "message", "content", "response", "output", "summary"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                last_text = value.strip()

    if chunks:
        return "\n".join(chunks).strip()
    if last_text:
        return last_text.strip()
    return raw.strip()[-8000:]


def _stderr_has_error(raw: str) -> str | None:
    if not raw:
        return None
    lowered = raw.lower()
    critical_markers = (
        "no endpoints found",
        "model not found",
        "provider not found",
        "authentication failed",
        "unauthorized",
        "invalid api key",
        "rate limit",
    )
    if any(marker in lowered for marker in critical_markers):
        cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw)
        return cleaned.strip()[-2000:]
    return None


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


_FILE_INTENT_RE = re.compile(
    r"(append|create|update|edit|write|open\s+up|inside\s+that)" \
    r".*\b([A-Za-z0-9_./-]+\.[A-Za-z0-9_+-]+)\b",
    re.IGNORECASE | re.DOTALL,
)


def _with_file_execution_contract(prompt: str) -> str:
    if not prompt or not _FILE_INTENT_RE.search(prompt):
        return prompt
    contract = (
        "Execution contract: You must actually perform the requested file operation in the workspace. "
        "Do not only describe what you would do. After editing, verify by reading the target file and return a concise completion summary."
    )
    return f"{prompt}\n\n{contract}"


def main() -> int:
    raw_input = sys.stdin.read()
    try:
        payload = json.loads(raw_input) if raw_input.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    prompt = _with_file_execution_contract(_safe_text(payload.get("prompt")))
    workspace_root = _safe_text(payload.get("workspace_root")) or str(Path.cwd())
    model = _safe_text(os.getenv("OPENAI_MODEL"))
    base_url = _safe_text(os.getenv("OPENAI_BASE_URL"))
    allow_model_fallback = _safe_text(os.getenv("OPENCODE_ALLOW_MODEL_FALLBACK")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    model_for_cli = model
    if model and "openrouter.ai" in base_url.lower() and not model.lower().startswith("openrouter/"):
        slash_count = model.count("/")
        if slash_count == 1:
            # OpenCode expects provider/model format. Convert "author/model" -> "openrouter/author/model".
            model_for_cli = f"openrouter/{model}"
        elif slash_count == 0:
            error_message = (
                "Invalid OpenRouter model id. Expected 'author/model' (for example: "
                "'nvidia/nemotron-3-super-120b-a12b:free' or 'qwen/qwen3.5-flash-02-23')."
            )
            result = {
                "success": False,
                "engine": "opencode",
                "model": "opencode",
                "provider_model": model,
                "response": error_message,
                "used_tools": [],
                "created_paths": [],
                "updated_paths": [],
                "artifacts": [],
                "error": error_message,
                "stderr": "",
                "raw_output": "",
            }
            sys.stdout.write(json.dumps(result, ensure_ascii=True))
            return 0

    def _run_once(selected_model: str | None) -> subprocess.CompletedProcess[str]:
        cmd = [
            opencode_bin,
            "run",
            prompt,
            "--pure",
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
    stderr_error = _stderr_has_error(stderr_text)
    if stream_error and "model not found" in stream_error.lower() and allow_model_fallback:
        # Optional: retry without forcing model when explicitly enabled.
        proc = _run_once(None)
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""
        success = proc.returncode == 0
        stream_error = _stream_has_error(stdout_text)
        stderr_error = _stderr_has_error(stderr_text)
    if stream_error:
        success = False
    if stderr_error:
        success = False

    extracted_response = _extract_response(stdout_text)
    if not success and stream_error:
        extracted_response = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stream_error)
    if not success and not stream_error and stderr_error:
        extracted_response = stderr_error

    result = {
        "success": success,
        "engine": "opencode",
        "model": "opencode",
        "provider_model": model or None,
        "response": extracted_response,
        "used_tools": _collect_tool_names(stdout_text),
        "created_paths": [],
        "updated_paths": [],
        "artifacts": [],
        "error": None if success else (stream_error or stderr_error or _safe_text(stderr_text) or f"opencode exited with code {proc.returncode}"),
        "stderr": stderr_text[-8000:],
        "raw_output": stdout_text[-16000:],
    }

    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
