from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid


@dataclass(slots=True)
class Diagnosis:
    hypothesis: str
    confidence: float
    suggested_fix: str


@dataclass(slots=True)
class FixAction:
    action_type: str
    target_id: str | None = None
    params: dict[str, Any] | None = None


@dataclass(slots=True)
class FixPlan:
    failure_id: str
    recommended_hypothesis: str
    risk_level: str
    requires_user_approval: bool
    actions: list[FixAction]
    notes: str


@dataclass(slots=True)
class EmergencyAnalysis:
    failure_id: str
    source: str
    error: str
    diagnoses: list[Diagnosis]
    fix_plan: FixPlan
    generated_at: str


class EmergencyModule:
    """Rule-based failure diagnosis for runtime and skill execution issues."""

    async def on_failure(self, event: dict[str, Any]) -> list[Diagnosis]:
        return self._diagnose(event)

    async def analyze_failure(self, event: dict[str, Any]) -> EmergencyAnalysis:
        failure_id = str(event.get("failure_id") or f"failure-{uuid.uuid4().hex[:12]}")
        source = str(event.get("source", "unknown"))
        error = str(event.get("error", "")).strip()
        diagnoses = self._diagnose(event)
        fix_plan = self._propose_fix_plan(event=event, failure_id=failure_id, diagnoses=diagnoses)
        return EmergencyAnalysis(
            failure_id=failure_id,
            source=source,
            error=error,
            diagnoses=diagnoses,
            fix_plan=fix_plan,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _propose_fix_plan(self, *, event: dict[str, Any], failure_id: str, diagnoses: list[Diagnosis]) -> FixPlan:
        top = max(diagnoses, key=lambda d: d.confidence)
        source = str(event.get("source", "unknown"))
        actions: list[FixAction] = []
        risk_level = "low"
        notes = "Apply low-risk actions first and re-run diagnostics."

        lower_hypothesis = top.hypothesis.lower()
        if "configured execution budget" in lower_hypothesis:
            actions.append(
                FixAction(
                    action_type="update_config",
                    params={"key": "orchestrator.skill_execution_timeout_s", "value": 30.0},
                )
            )
            risk_level = "medium"
            notes = "Timeout tuning may increase runtime cost; apply with approval and monitor."
        elif "blocked" in lower_hypothesis:
            skill_id = event.get("skill_id")
            actions.append(
                FixAction(
                    action_type="update_config",
                    params={"key": "execution.allowed_command_prefixes", "value": ["python", "git", "echo"]},
                )
            )
            if skill_id:
                actions.append(FixAction(action_type="disable_skill", target_id=str(skill_id)))
            risk_level = "medium"
            notes = "Policy updates can broaden execution scope; prefer targeted allowlist changes."
        elif "not assigned" in lower_hypothesis:
            skill_id = event.get("skill_id")
            if skill_id:
                actions.append(FixAction(action_type="disable_skill", target_id=str(skill_id)))
            risk_level = "low"
            notes = "Re-assign skill to the correct agent before re-enabling it."
        else:
            actions.append(FixAction(action_type="restart_module", target_id=source))

        return FixPlan(
            failure_id=failure_id,
            recommended_hypothesis=top.hypothesis,
            risk_level=risk_level,
            requires_user_approval=True,
            actions=actions,
            notes=notes,
        )

    def _diagnose(self, event: dict[str, Any]) -> list[Diagnosis]:
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
