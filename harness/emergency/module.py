from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Diagnosis:
    hypothesis: str
    confidence: float
    suggested_fix: str


class EmergencyModule:
    """Rule-based failure diagnosis for runtime and skill execution issues."""

    async def on_failure(self, event: dict[str, Any]) -> list[Diagnosis]:
        source = str(event.get("source", "unknown"))
        error = str(event.get("error", "")).strip()
        lower_error = error.lower()
        diagnoses: list[Diagnosis] = []

        if "timed out" in lower_error or "timeout" in lower_error:
            diagnoses.append(
                Diagnosis(
                    hypothesis=f"{source} exceeded its configured execution budget",
                    confidence=0.9,
                    suggested_fix="Reduce task scope, optimize the handler, or increase orchestrator.skill_execution_timeout_s",
                )
            )

        if "not assigned to agent" in lower_error:
            diagnoses.append(
                Diagnosis(
                    hypothesis="Agent tried to execute a skill that was not assigned",
                    confidence=0.95,
                    suggested_fix="Assign the skill to the target agent before execution",
                )
            )

        if "blocked by execution policy" in lower_error or "blocked by deny-all policy" in lower_error:
            diagnoses.append(
                Diagnosis(
                    hypothesis="Execution policy blocked the requested tool or command",
                    confidence=0.95,
                    suggested_fix="Update tool allowlists or execution.allowed_command_prefixes before retrying",
                )
            )

        if "no such file" in lower_error or "cannot find the file specified" in lower_error:
            diagnoses.append(
                Diagnosis(
                    hypothesis="The requested executable is not available in the current environment",
                    confidence=0.85,
                    suggested_fix="Use a configured command prefix that resolves on this host, or install the missing executable",
                )
            )

        if not diagnoses:
            diagnoses.append(
                Diagnosis(
                    hypothesis=f"Failure observed from {source}",
                    confidence=0.3,
                    suggested_fix="Inspect logs and restart affected module",
                )
            )

        return diagnoses
