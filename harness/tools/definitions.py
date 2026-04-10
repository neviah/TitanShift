from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    required_paths: list[str] = field(default_factory=list)
    needs_network: bool = False
    handler: ToolHandler | None = None
