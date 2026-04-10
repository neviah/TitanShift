from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class JsonLogger:
    log_file: Path

    def __post_init__(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def query(
        self,
        *,
        event_type: str | None = None,
        task_id: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.log_file.exists():
            return []

        matched: list[dict[str, Any]] = []
        with self.log_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                payload = record.get("payload", {}) if isinstance(record.get("payload", {}), dict) else {}
                if event_type and record.get("event_type") != event_type:
                    continue
                if task_id and payload.get("task_id") != task_id:
                    continue
                if source and payload.get("source") != source:
                    continue
                matched.append(record)

        return matched[-max(1, limit) :]
