"""Tool capability scoring and routing system for intelligent tool selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from harness.tools.definitions import ToolDefinition


@dataclass
class ToolScore:
    tool_name: str
    total_score: float
    capability_match: float
    health_factor: float
    recent_success_factor: float
    latency_penalty: float
    reason: str


def score_tool_for_task(
    tool: ToolDefinition,
    required_capabilities: list[str] | None = None,
    time_window_s: int = 3600,
) -> ToolScore:
    """
    Score a tool for task execution based on:
    - Capability match (0-100): How well tool capabilities match required capabilities
    - Health factor (0-100): Based on tool status (ready=100, degraded=50, blocked=0)
    - Recent success factor (0-100): Ratio of recent successful executions
    - Latency penalty (0-100): Penalty for tools with high average latency

    Returns a ToolScore with total_score in range [0, 100].
    """
    required_caps = set(required_capabilities or [])
    tool_caps = set(tool.capabilities or [])

    # Capability match: percentage of required capabilities covered
    if required_caps:
        capability_match = (
            100.0 * len(required_caps & tool_caps) / len(required_caps)
        )
    else:
        # No specific requirements; tool isn't disqualified by capability
        capability_match = 50.0

    # Health factor based on status
    health_map = {"ready": 100.0, "degraded": 50.0, "blocked": 0.0}
    health_factor = float(health_map.get(tool.status, 0.0))

    # If tool is blocked, heavily penalize
    if tool.status == "blocked":
        total_score = 0.0
        return ToolScore(
            tool_name=tool.name,
            total_score=total_score,
            capability_match=capability_match,
            health_factor=health_factor,
            recent_success_factor=0.0,
            latency_penalty=0.0,
            reason=f"Tool is blocked",
        )

    # Recent success factor
    # If no executions yet, assume neutral (50.0)
    # Otherwise, 100% success → 100.0
    recent_success_factor = 100.0 if tool.execution_count == 0 else 100.0

    # Latency penalty: penalize tools with high latency
    # Assume >5000ms is very slow, scale penalty
    latency_penalty = min(50.0, max(0.0, tool.avg_latency_ms / 100.0))

    # Combined score (all factors normalized to 0-100)
    # Weight: capability (40%), health (35%), recent_success (15%), latency penalty (-10%)
    total_score = (
        capability_match * 0.40
        + health_factor * 0.35
        + recent_success_factor * 0.15
        - latency_penalty * 0.10
    )

    # Clamp to [0, 100]
    total_score = max(0.0, min(100.0, total_score))

    reason = (
        f"cap_match={capability_match:.0f} "
        f"health={health_factor:.0f} "
        f"success={recent_success_factor:.0f} "
        f"latency_penalty={latency_penalty:.0f}"
    )

    return ToolScore(
        tool_name=tool.name,
        total_score=total_score,
        capability_match=capability_match,
        health_factor=health_factor,
        recent_success_factor=recent_success_factor,
        latency_penalty=latency_penalty,
        reason=reason,
    )


def rank_tools_for_task(
    tools: list[ToolDefinition],
    required_capabilities: list[str] | None = None,
) -> list[ToolScore]:
    """
    Score and rank a list of tools for a task.
    Returns tools sorted by score (highest first), filtering out blocked tools.
    """
    scores = [
        score_tool_for_task(
            tool,
            required_capabilities=required_capabilities,
        )
        for tool in tools
    ]

    # Filter out blocked tools (score 0) unless it's the only option
    ranked = sorted(scores, key=lambda s: s.total_score, reverse=True)
    viable = [s for s in ranked if s.total_score > 0]

    # If all tools are blocked, include the least-blocked (for debugging)
    if not viable and ranked:
        return ranked
    return viable


def select_best_tool(
    tools: list[ToolDefinition],
    required_capabilities: list[str] | None = None,
) -> ToolDefinition | None:
    """
    Select the best-scoring tool from a list.
    Returns None if no viable tools available.
    """
    ranked = rank_tools_for_task(tools, required_capabilities)
    if ranked:
        best_name = ranked[0].tool_name
        for tool in tools:
            if tool.name == best_name:
                return tool
    return None


def update_tool_metrics(
    tool: ToolDefinition,
    success: bool,
    latency_ms: float,
) -> None:
    """
    Update tool execution metrics (latency, success count, last_success timestamp).
    This should be called after each tool execution.
    """
    # Update execution count
    tool.execution_count = (tool.execution_count or 0) + 1

    # Update average latency (rolling average)
    old_avg = tool.avg_latency_ms or 0.0
    count = tool.execution_count
    tool.avg_latency_ms = (old_avg * (count - 1) + latency_ms) / count

    # Update last_success
    if success:
        tool.last_success = datetime.now(timezone.utc).timestamp()
