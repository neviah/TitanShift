"""
Telemetry tracking for tool execution and orchestration runs.

Tracks: requested tools, attempted tools, failures, fallbacks, execution time.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RunTelemetry:
    """Telemetry for a single orchestration run."""

    run_id: str
    task_id: str | None = None
    agent_id: str = "main-agent"
    requested_tool: str | None = None  # Tool explicitly requested by user/model
    attempted_tools: list[str] = field(default_factory=list)  # Tools tried in order
    primary_tool: str | None = None  # First tool attempted
    primary_failure_reason: str | None = None  # Why the first tool failed
    fallback_used: bool = False  # Did we fall back to alternative tool?
    succeeded_tool: str | None = None  # Which tool ultimately succeeded
    tool_count: int = 0
    started_at: str = ""
    completed_at: str | None = None
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/API."""
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "requested_tool": self.requested_tool,
            "attempted_tools": self.attempted_tools,
            "primary_tool": self.primary_tool,
            "primary_failure_reason": self.primary_failure_reason,
            "fallback_used": self.fallback_used,
            "succeeded_tool": self.succeeded_tool,
            "tool_count": self.tool_count,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            **self.extra,
        }


class TelemetryCollector:
    """Collects and stores telemetry across runs."""

    def __init__(self):
        self.runs: dict[str, RunTelemetry] = {}
        self._max_runs = 1000

    def create_run(self, run_id: str, task_id: str | None = None) -> RunTelemetry:
        """Create a new run telemetry record."""
        telemetry = RunTelemetry(
            run_id=run_id,
            task_id=task_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.runs[run_id] = telemetry
        # Keep only recent runs to avoid memory bloat
        if len(self.runs) > self._max_runs:
            oldest_key = min(self.runs.keys(), key=lambda k: self.runs[k].started_at)
            del self.runs[oldest_key]
        return telemetry

    def get_run(self, run_id: str) -> RunTelemetry | None:
        """Get telemetry for a specific run."""
        return self.runs.get(run_id)

    def record_tool_attempt(self, run_id: str, tool_name: str, is_primary: bool = False) -> None:
        """Record an attempt to execute a tool."""
        telemetry = self.runs.get(run_id)
        if not telemetry:
            return
        if tool_name not in telemetry.attempted_tools:
            telemetry.attempted_tools.append(tool_name)
        if is_primary and not telemetry.primary_tool:
            telemetry.primary_tool = tool_name

    def record_tool_failure(
        self, run_id: str, tool_name: str, reason: str, is_primary: bool = False
    ) -> None:
        """Record a tool execution failure."""
        telemetry = self.runs.get(run_id)
        if not telemetry:
            return
        if is_primary and not telemetry.primary_failure_reason:
            telemetry.primary_failure_reason = reason
        if tool_name not in telemetry.attempted_tools:
            telemetry.attempted_tools.append(tool_name)

    def record_tool_success(self, run_id: str, tool_name: str) -> None:
        """Record successful tool execution."""
        telemetry = self.runs.get(run_id)
        if not telemetry:
            return
        telemetry.succeeded_tool = tool_name
        if tool_name not in telemetry.attempted_tools:
            telemetry.attempted_tools.append(tool_name)

    def record_fallback(self, run_id: str) -> None:
        """Record that a fallback was used."""
        telemetry = self.runs.get(run_id)
        if telemetry:
            telemetry.fallback_used = True

    def finalize_run(self, run_id: str) -> None:
        """Mark run as complete and compute final metrics."""
        telemetry = self.runs.get(run_id)
        if not telemetry:
            return
        telemetry.completed_at = datetime.now(timezone.utc).isoformat()
        if telemetry.started_at:
            start = datetime.fromisoformat(telemetry.started_at)
            end = datetime.fromisoformat(telemetry.completed_at)
            telemetry.duration_ms = int((end - start).total_seconds() * 1000)
        telemetry.tool_count = len(telemetry.attempted_tools)

    def list_recent_runs(self, limit: int = 50) -> list[RunTelemetry]:
        """Get recent runs, sorted by start time (newest first)."""
        runs = list(self.runs.values())
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs[:limit]
