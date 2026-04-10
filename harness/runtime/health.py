from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class HealthRecord:
    name: str
    status: str
    updated_at: str
    details: dict[str, Any]


class HealthRegistry:
    def __init__(self) -> None:
        self._records: dict[str, HealthRecord] = {}

    def set(self, name: str, status: str, details: dict[str, Any] | None = None) -> None:
        self._records[name] = HealthRecord(
            name=name,
            status=status,
            updated_at=datetime.now(timezone.utc).isoformat(),
            details=details or {},
        )

    def as_list(self) -> list[dict[str, Any]]:
        return [asdict(v) for v in sorted(self._records.values(), key=lambda r: r.name)]
