from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.runtime.types import Task, TaskResult


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    description: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    success: bool | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS harness_tasks (
    task_id      TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    status       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    success      INTEGER,
    output_json  TEXT,
    error        TEXT
)
"""

_UPSERT_SQL = """
INSERT OR REPLACE INTO harness_tasks
    (task_id, description, status, created_at, started_at, completed_at, success, output_json, error)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_ALL_SQL = """
SELECT task_id, description, status, created_at, started_at, completed_at, success, output_json, error
FROM harness_tasks
"""


class TaskStore:
    """In-memory task store with optional SQLite persistence.

    When *db_path* is provided the store creates (or opens) a SQLite database
    at that path, pre-loads all existing rows into the in-memory cache, and
    writes every mutation through to the database.  When *db_path* is ``None``
    the store operates entirely in-memory (useful for tests that don't need
    durability).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            self._init_db(db_path)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _init_db(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()
        # Warm the in-memory cache from existing rows
        for row in self._conn.execute(_SELECT_ALL_SQL).fetchall():
            task_id, description, status, created_at, started_at, completed_at, success_int, output_json, error = row
            self._records[task_id] = TaskRecord(
                task_id=task_id,
                description=description,
                status=status,
                created_at=created_at,
                started_at=started_at,
                completed_at=completed_at,
                success=None if success_int is None else bool(success_int),
                output=json.loads(output_json) if output_json else {},
                error=error,
            )

    def _persist(self, record: TaskRecord) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            _UPSERT_SQL,
            (
                record.task_id,
                record.description,
                record.status,
                record.created_at,
                record.started_at,
                record.completed_at,
                None if record.success is None else int(record.success),
                json.dumps(record.output, default=str),
                record.error,
            ),
        )
        self._conn.commit()

    # ── Public interface ──────────────────────────────────────────────────────

    def create(self, task: Task) -> TaskRecord:
        record = TaskRecord(
            task_id=task.id,
            description=task.description,
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._records[task.id] = record
        self._persist(record)
        return record

    def mark_started(self, task_id: str) -> None:
        record = self._records[task_id]
        record.status = "running"
        record.started_at = datetime.now(timezone.utc).isoformat()
        self._persist(record)

    def mark_completed(self, result: TaskResult) -> None:
        record = self._records[result.task_id]
        record.status = "completed" if result.success else "failed"
        record.completed_at = datetime.now(timezone.utc).isoformat()
        record.success = result.success
        record.output = result.output
        record.error = result.error
        self._persist(record)

    def mark_cancelled(self, task_id: str) -> None:
        record = self._records.get(task_id)
        if record is None:
            return
        record.status = "cancelled"
        record.completed_at = datetime.now(timezone.utc).isoformat()
        record.success = False
        record.error = "Cancelled"
        self._persist(record)

    def list(self) -> list[TaskRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)

    def get(self, task_id: str) -> TaskRecord | None:
        return self._records.get(task_id)
