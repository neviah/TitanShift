from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


ArtifactBackendHandler = Callable[["ArtifactRenderRequest"], Awaitable["ArtifactRenderResult"]]


@dataclass(slots=True)
class ArtifactRenderRequest:
    backend: str
    generator: str
    args: dict[str, Any]


@dataclass(slots=True)
class ArtifactRenderResult:
    backend: str
    payload: dict[str, Any]
    artifacts: list[dict[str, Any]] = field(default_factory=list)


class ArtifactBackendRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ArtifactBackendHandler] = {}

    def register(self, name: str, handler: ArtifactBackendHandler) -> None:
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("backend name is required")
        self._handlers[normalized] = handler

    def unregister(self, name: str) -> bool:
        return self._handlers.pop(str(name).strip(), None) is not None

    def has_backend(self, name: str) -> bool:
        return str(name).strip() in self._handlers

    def list_backends(self) -> list[str]:
        return sorted(self._handlers.keys())

    async def render(self, request: ArtifactRenderRequest) -> ArtifactRenderResult:
        handler = self._handlers.get(request.backend)
        if handler is None:
            raise KeyError(f"Artifact backend not found: {request.backend}")
        return await handler(request)