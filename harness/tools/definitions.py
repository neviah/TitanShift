from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    required_paths: list[str] = field(default_factory=list)
    required_commands: list[str] = field(default_factory=list)
    needs_network: bool = False
    handler: ToolHandler | None = None
    parameters: dict | None = None  # JSON Schema for tool arguments
    capabilities: list[str] = field(default_factory=list)  # e.g., ["http.rest", "api.query", "json.parse"]
    status: str = "ready"  # ready, degraded, blocked
    last_success: float | None = None  # timestamp of last successful execution
    execution_count: int = 0  # total executions for this session
    avg_latency_ms: float = 0.0  # average execution latency
