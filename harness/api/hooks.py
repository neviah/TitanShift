from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class HookPayload:
    event: str
    data: dict[str, Any]


class ApiHooks:
    """Thin event surface to wire FastAPI/WebSocket later without refactoring core."""

    def __init__(self) -> None:
        self._hooks: dict[str, list] = {}

    def register(self, event: str, callback) -> None:
        self._hooks.setdefault(event, []).append(callback)

    async def emit(self, payload: HookPayload) -> None:
        for callback in self._hooks.get(payload.event, []):
            maybe = callback(payload.data)
            if hasattr(maybe, "__await__"):
                await maybe
