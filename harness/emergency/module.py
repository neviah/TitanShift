from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Diagnosis:
    hypothesis: str
    confidence: float
    suggested_fix: str


class EmergencyModule:
    """Phase 1 stub: detect and report, no auto-fix execution yet."""

    async def on_failure(self, event: dict[str, Any]) -> list[Diagnosis]:
        return [
            Diagnosis(
                hypothesis=f"Failure observed from {event.get('source', 'unknown')}",
                confidence=0.3,
                suggested_fix="Inspect logs and restart affected module",
            )
        ]
