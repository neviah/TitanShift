from __future__ import annotations

import json as _json
import re
from dataclasses import dataclass, field
from typing import Any
from typing import Protocol

import httpx

from harness.runtime.config import ConfigManager


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ModelRequest:
    prompt: str
    system_prompt: str | None = None
    available_tools: list[dict[str, str]] | None = None  # legacy compat
    messages: list[dict[str, Any]] | None = None          # multi-turn; overrides prompt when set
    tool_definitions: list[dict[str, Any]] | None = None  # full OpenAI-format tool schemas


@dataclass(slots=True)
class ModelResponse:
    text: str
    model_id: str
    tool_calls: list[ToolCall] | None = None


class ModelAdapter(Protocol):
    model_id: str

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    def estimate_tokens(self, text: str) -> int: ...


class LocalStubAdapter:
    model_id = "local_stub"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text=f"[local_stub] {request.prompt}",
            model_id=self.model_id,
        )

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


class CloudOpenAIAdapter:
    """Cloud adapter stub kept optional by config and environment setup."""

    model_id = "openai_compatible"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError("Cloud adapter is a scaffold stub in phase 1")

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


class LMStudioAdapter:
    """OpenAI-compatible local adapter for LM Studio server."""

    model_id = "lmstudio"

    def __init__(self, base_url: str, default_model: str, timeout_s: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_s = timeout_s

    async def generate(self, request: ModelRequest) -> ModelResponse:
        # Build message list — prefer multi-turn messages if provided
        if request.messages is not None:
            messages = request.messages
        else:
            messages = [
                {"role": "system", "content": request.system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": request.prompt},
            ]

        payload: dict[str, Any] = {
            "model": self.default_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 512,
        }

        # Full tool schemas take priority; fall back to legacy available_tools stub
        if request.tool_definitions:
            payload["tools"] = request.tool_definitions
            payload["tool_choice"] = "auto"
        elif request.available_tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", "unknown"),
                        "description": t.get("description", ""),
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                }
                for t in request.available_tools
            ]
            payload["tool_choice"] = "auto"

        endpoint = f"{self.base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "LM Studio timed out while generating a response. "
                f"Endpoint: {endpoint}. Timeout: {self.timeout_s}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text if exc.response is not None else ""
            body_snippet = re.sub(r"\s+", " ", body).strip()[:400]
            raise RuntimeError(
                "LM Studio rejected chat request "
                f"({exc.response.status_code if exc.response is not None else 'unknown'}). "
                f"Endpoint: {endpoint}. Response: {body_snippet or 'no response body'}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                "LM Studio request failed. Ensure LM Studio server is running and the OpenAI-compatible "
                f"endpoint is reachable at {endpoint}. Cause: {exc}"
            ) from exc

        body = response.json()
        choice0 = body.get("choices", [{}])[0]
        message0 = choice0.get("message", {})

        # Check for tool calls first
        raw_tool_calls = message0.get("tool_calls") or []
        if raw_tool_calls:
            tool_calls: list[ToolCall] = []
            for i, tc in enumerate(raw_tool_calls):
                fn = tc.get("function", {})
                try:
                    args = _json.loads(fn.get("arguments", "{}") or "{}")
                except Exception:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    name=fn.get("name", ""),
                    arguments=args,
                ))
            return ModelResponse(text="", model_id=self.model_id, tool_calls=tool_calls)

        content = str(message0.get("content", "")).strip() or str(message0.get("reasoning_content", "")).strip()
        if not content:
            content = "[lmstudio] empty response"
        return ModelResponse(text=content, model_id=self.model_id)

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


class ModelRegistry:
    def __init__(self, adapters: dict[str, ModelAdapter], default_backend: str) -> None:
        self.adapters = adapters
        self.default_backend = default_backend

    @classmethod
    def from_config(cls, cfg: ConfigManager) -> "ModelRegistry":
        lmstudio_base_url = cfg.get("model.lmstudio.base_url", "http://127.0.0.1:1234/v1")
        lmstudio_model = cfg.get("model.lmstudio.model", "local-model")
        lmstudio_timeout = float(cfg.get("model.lmstudio.timeout_s", 45.0))
        adapters: dict[str, ModelAdapter] = {
            "local_stub": LocalStubAdapter(),
            "openai_compatible": CloudOpenAIAdapter(),
            "lmstudio": LMStudioAdapter(
                base_url=lmstudio_base_url,
                default_model=lmstudio_model,
                timeout_s=lmstudio_timeout,
            ),
        }
        default_backend = cfg.get("model.default_backend", "local_stub")
        return cls(adapters=adapters, default_backend=default_backend)

    def select_model(self, preferred: str | None = None) -> ModelAdapter:
        backend = preferred or self.default_backend
        if backend not in self.adapters:
            backend = "local_stub"
        return self.adapters[backend]


def check_lmstudio_health(cfg: ConfigManager) -> dict[str, Any]:
    """Performs endpoint check, model list check, and tiny inference check."""

    base_url = str(cfg.get("model.lmstudio.base_url", "http://127.0.0.1:1234/v1")).rstrip("/")
    model_id = str(cfg.get("model.lmstudio.model", "local-model"))
    timeout_s = float(cfg.get("model.lmstudio.timeout_s", 45.0))

    models_url = f"{base_url}/models"
    chat_url = f"{base_url}/chat/completions"

    with httpx.Client(timeout=timeout_s) as client:
        models_resp = client.get(models_url)
        models_resp.raise_for_status()
        models_body = models_resp.json()
        listed_ids = [m.get("id", "") for m in models_body.get("data", [])]
        model_present = model_id in listed_ids

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": "Reply with exactly: CHECK_OK"},
            ],
            "temperature": 0.0,
            "max_tokens": 32,
            "reasoning": "off",
        }
        chat_resp = client.post(chat_url, json=payload)
        chat_resp.raise_for_status()
        chat_body = chat_resp.json()
        choice0 = chat_body.get("choices", [{}])[0]
        msg = choice0.get("message", {})
        content = str(msg.get("content", "")).strip() or str(msg.get("reasoning_content", "")).strip()
        finish_reason = str(choice0.get("finish_reason", ""))

    return {
        "ok": True,
        "base_url": base_url,
        "configured_model": model_id,
        "model_present": model_present,
        "available_models": listed_ids,
        "inference_reply": content,
        "finish_reason": finish_reason,
    }
