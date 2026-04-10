from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from harness.runtime.config import ConfigManager


@dataclass(slots=True)
class ModelRequest:
    prompt: str
    system_prompt: str | None = None


@dataclass(slots=True)
class ModelResponse:
    text: str
    model_id: str


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
        payload = {
            "model": self.default_model,
            "messages": [
                {"role": "system", "content": request.system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": 0.2,
        }
        endpoint = f"{self.base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                "LM Studio request failed. Ensure LM Studio server is running and the OpenAI-compatible "
                f"endpoint is reachable at {endpoint}"
            ) from exc
        body = response.json()
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
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
