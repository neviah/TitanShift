from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable


@dataclass(slots=True)
class HookPayload:
    event: str
    data: dict[str, Any]


@dataclass(slots=True)
class HookRegistration:
    event: str
    label: str
    callback: Callable[[dict[str, Any]], Any]
    priority: int = 50
    timeout_s: float = 10.0


class ApiHooks:
    """Thin event surface to wire FastAPI/WebSocket later without refactoring core."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookRegistration]] = {}
        self._next_id = 0

    def register(
        self,
        event: str,
        callback: Callable[[dict[str, Any]], Any],
        *,
        priority: int = 50,
        timeout_s: float = 10.0,
        label: str | None = None,
    ) -> str:
        normalized_event = str(event).strip()
        if not normalized_event:
            raise ValueError("event is required")
        self._next_id += 1
        registration = HookRegistration(
            event=normalized_event,
            label=label or f"{normalized_event}:{self._next_id}",
            callback=callback,
            priority=int(priority),
            timeout_s=max(0.0, float(timeout_s)),
        )
        bucket = self._hooks.setdefault(normalized_event, [])
        bucket.append(registration)
        bucket.sort(key=lambda row: (row.priority, row.label))
        return registration.label

    def unregister(self, *, label: str) -> bool:
        removed = False
        for event, registrations in self._hooks.items():
            remaining = [row for row in registrations if row.label != label]
            if len(remaining) != len(registrations):
                self._hooks[event] = remaining
                removed = True
        return removed

    async def _invoke(self, registration: HookRegistration, data: dict[str, Any]) -> Any:
        maybe = registration.callback(data)
        if hasattr(maybe, "__await__"):
            coroutine = maybe if isinstance(maybe, Awaitable) else maybe
            if registration.timeout_s > 0:
                return await asyncio.wait_for(coroutine, timeout=registration.timeout_s)
            return await coroutine
        return maybe

    async def emit(self, payload: HookPayload) -> None:
        for registration in self._hooks.get(payload.event, []):
            try:
                await self._invoke(registration, payload.data)
            except Exception:
                continue

    async def execute(self, event: str, data: dict[str, Any]) -> list[Any]:
        results: list[Any] = []
        for registration in self._hooks.get(str(event).strip(), []):
            try:
                results.append(await self._invoke(registration, data))
            except Exception as exc:
                results.append(
                    {
                        "action": "error",
                        "label": registration.label,
                        "error": str(exc),
                    }
                )
        return results
