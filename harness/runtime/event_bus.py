from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """Async pub/sub event bus for module decoupling."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return
        await asyncio.gather(*(h(payload) for h in handlers), return_exceptions=True)
