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
    timeout_s: float | None = None


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
    """Generic OpenAI-compatible adapter (OpenRouter, Ollama, local gateways)."""

    model_id = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        default_model: str,
        timeout_s: float = 45.0,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        api_key: str = "",
        provider_name: str = "OpenAI-compatible provider",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_s = timeout_s
        self.max_tokens = max(128, int(max_tokens))
        self.temperature = float(temperature)
        self.api_key = api_key.strip()
        self.provider_name = provider_name
        self.extra_headers = extra_headers or {}

    @staticmethod
    def _parse_loose_arguments(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if not text:
            return {}
        if text.startswith("{"):
            try:
                loaded = _json.loads(text)
                return loaded if isinstance(loaded, dict) else {}
            except Exception:
                return {}

        args: dict[str, Any] = {}
        pattern = re.compile(r'["\']?([\w-]+)["\']?\s*:\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^,]+)(?:,|$)')
        for match in pattern.finditer(text):
            key = match.group(1)
            raw_value = match.group(2).strip()
            if (raw_value.startswith('"') and raw_value.endswith('"')) or (raw_value.startswith("'") and raw_value.endswith("'")):
                value: Any = raw_value[1:-1]
            elif raw_value.lower() in {'true', 'false'}:
                value = raw_value.lower() == 'true'
            else:
                try:
                    value = int(raw_value) if raw_value.isdigit() else float(raw_value)
                except ValueError:
                    value = raw_value
            args[key] = value
        return args

    def _extract_pseudo_tool_calls(self, content: str) -> list[ToolCall]:
        text = content.strip()
        if not text:
            return []

        segments: list[str] = []
        for pattern in [
            r'<\|tool_call\|>(.*?)<\|tool_call\|>',
            r'<tool_call>(.*?)</tool_call>',
            r'<\|tool_call>(.*?)<tool_call\|>',
            r'<\|tool_call>(.*?)<\|tool_call\|>',
            r'<\|tool_call\|>(.*?)<tool_call\|>',
            r'<tool_call>(.*?)<tool_call\|>',
            r'<\|tool_call\|>(.*?)<tool_call>',
            r'<tool_call>(.*?)<\|tool_call\|>',
            r'<\|tool_call>(.*?)<tool_call>',
            r'<tool_call>(.*?)<\|tool_call>',
            r'<\|tool_call\|>(.*)$',
            r'<\|tool_call>(.*)$',
            r'<tool_call\|>(.*)$',
            r'<tool_call>(.*)$',
        ]:
            segments.extend(match.group(1).strip() for match in re.finditer(pattern, text, re.DOTALL | re.IGNORECASE))

        if not segments:
            if 'call:' in text:
                segments = [text]
            else:
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                segments.extend([line for line in lines if line.lower().startswith('tool_call') or 'call:' in line.lower()])

        tool_calls: list[ToolCall] = []
        seen: set[tuple[str, str]] = set()
        for index, segment in enumerate(segments):
            # Try parentheses first, then curly-brace argument syntax
            match = re.search(r'call:([a-zA-Z0-9_.:-]+)\s*\((.*)\)', segment, re.DOTALL)
            if not match:
                match = re.search(r'call:([a-zA-Z0-9_.:-]+)\s*\{(.*)\}', segment, re.DOTALL)
            if not match:
                continue
            raw_name = match.group(1).strip()
            # Normalize provider-specific dotted names into registry-safe identifiers.
            normalized_name = raw_name.replace('.', '_').replace(':', '_')
            raw_args = match.group(2)
            identity = (normalized_name, raw_args.strip())
            if identity in seen:
                continue
            seen.add(identity)
            tool_calls.append(ToolCall(
                id=f'content_call_{index}',
                name=normalized_name,
                arguments=self._parse_loose_arguments(raw_args),
            ))
        return tool_calls

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

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
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
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
        effective_timeout = float(request.timeout_s) if request.timeout_s is not None else self.timeout_s
        try:
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                response = await client.post(endpoint, json=payload, headers=self._build_headers())
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"{self.provider_name} timed out while generating a response. "
                f"Endpoint: {endpoint}. Timeout: {effective_timeout}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text if exc.response is not None else ""
            body_snippet = re.sub(r"\s+", " ", body).strip()[:400]
            raise RuntimeError(
                f"{self.provider_name} rejected chat request "
                f"({exc.response.status_code if exc.response is not None else 'unknown'}). "
                f"Endpoint: {endpoint}. Response: {body_snippet or 'no response body'}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"{self.provider_name} request failed. Ensure the endpoint is reachable at {endpoint}. "
                f"Cause: {exc}"
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
        parsed_tool_calls = self._extract_pseudo_tool_calls(content)
        if parsed_tool_calls:
            return ModelResponse(text="", model_id=self.model_id, tool_calls=parsed_tool_calls)
        # Strip any unprocessed tool-call markup so raw syntax never reaches the chat UI
        _cleaned = re.sub(r'<\|?tool_call\|?>.*', '', content, flags=re.DOTALL | re.IGNORECASE).strip()
        content = _cleaned if _cleaned else content
        if not content:
            content = "[openai_compatible] empty response"
        return ModelResponse(text=content, model_id=self.model_id)

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


class LMStudioAdapter:
    """OpenAI-compatible local adapter for LM Studio server."""

    model_id = "lmstudio"

    def __init__(
        self,
        base_url: str,
        default_model: str,
        timeout_s: float = 45.0,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> None:
        self._delegate = CloudOpenAIAdapter(
            base_url=base_url,
            default_model=default_model,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key="",
            provider_name="LM Studio",
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        response = await self._delegate.generate(request)
        return ModelResponse(text=response.text, model_id=self.model_id, tool_calls=response.tool_calls)

    def _extract_pseudo_tool_calls(self, content: str) -> list[ToolCall]:
        return self._delegate._extract_pseudo_tool_calls(content)

    def estimate_tokens(self, text: str) -> int:
        return self._delegate.estimate_tokens(text)


class ModelRegistry:
    def __init__(self, adapters: dict[str, ModelAdapter], default_backend: str) -> None:
        self.adapters = adapters
        self.default_backend = default_backend

    @classmethod
    def from_config(cls, cfg: ConfigManager) -> "ModelRegistry":
        lmstudio_base_url = cfg.get("model.lmstudio.base_url", "http://127.0.0.1:1234/v1")
        lmstudio_model = cfg.get("model.lmstudio.model", "local-model")
        lmstudio_timeout = float(cfg.get("model.lmstudio.timeout_s", 45.0))
        lmstudio_max_tokens = int(cfg.get("model.lmstudio.max_tokens", 2048))
        lmstudio_temperature = float(cfg.get("model.lmstudio.temperature", 0.2))
        cloud_base_url = str(cfg.get("model.openai_compatible.base_url", "https://openrouter.ai/api/v1")).strip()
        cloud_model = str(cfg.get("model.openai_compatible.model", "openai/gpt-4o-mini")).strip()
        cloud_timeout = float(cfg.get("model.openai_compatible.timeout_s", 45.0))
        cloud_max_tokens = int(cfg.get("model.openai_compatible.max_tokens", 2048))
        cloud_temperature = float(cfg.get("model.openai_compatible.temperature", 0.2))
        cloud_api_key = str(cfg.get("model.openai_compatible.api_key", "")).strip()
        cloud_referrer = str(cfg.get("model.openai_compatible.referrer", "")).strip()
        cloud_title = str(cfg.get("model.openai_compatible.app_title", "TitanShift")).strip()
        cloud_headers: dict[str, str] = {}
        if cloud_referrer:
            cloud_headers["HTTP-Referer"] = cloud_referrer
        if cloud_title:
            cloud_headers["X-Title"] = cloud_title
        adapters: dict[str, ModelAdapter] = {
            "local_stub": LocalStubAdapter(),
            "openai_compatible": CloudOpenAIAdapter(
                base_url=cloud_base_url,
                default_model=cloud_model,
                timeout_s=cloud_timeout,
                max_tokens=cloud_max_tokens,
                temperature=cloud_temperature,
                api_key=cloud_api_key,
                provider_name="OpenAI-compatible provider",
                extra_headers=cloud_headers,
            ),
            "lmstudio": LMStudioAdapter(
                base_url=lmstudio_base_url,
                default_model=lmstudio_model,
                timeout_s=lmstudio_timeout,
                max_tokens=lmstudio_max_tokens,
                temperature=lmstudio_temperature,
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
