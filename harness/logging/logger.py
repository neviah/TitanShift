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
        agent_id: str | None = None,
        skill_id: str | None = None,
        execution_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.log_file.exists():
            return []

        def _parse_timestamp(value: str | None) -> datetime | None:
            if not value:
                return None
            candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                return None

        after_dt = _parse_timestamp(after)
        before_dt = _parse_timestamp(before)
        clamped_offset = max(0, offset)

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
                record_timestamp = _parse_timestamp(str(record.get("timestamp", "")))
                if event_type and record.get("event_type") != event_type:
                    continue
                if task_id and payload.get("task_id") != task_id:
                    continue
                if source and payload.get("source") != source:
                    continue
                if agent_id and payload.get("agent_id") != agent_id:
                    continue
                if skill_id and payload.get("skill_id") != skill_id:
                    continue
                if execution_id and payload.get("execution_id") != execution_id:
                    continue
                if after_dt and (record_timestamp is None or record_timestamp < after_dt):
                    continue
                if before_dt and (record_timestamp is None or record_timestamp > before_dt):
                    continue
                matched.append(record)

        end = max(0, len(matched) - clamped_offset)
        start = max(0, end - max(1, limit))
        return matched[start:end]
