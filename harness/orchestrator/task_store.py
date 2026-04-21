from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.migrations.runner import apply_migrations, check_version
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
    tenant_id: str = "_system_"


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
    (task_id, description, status, created_at, started_at, completed_at, success, output_json, error, tenant_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_ALL_SQL = """
SELECT task_id, description, status, created_at, started_at, completed_at, success, output_json, error,
       COALESCE(tenant_id, '_system_') AS tenant_id
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
        # Guard: raise MigrationError if the on-disk schema is ahead of our migrations
        check_version(self._conn, "task_store")
        # Apply any pending migrations (idempotent)
        apply_migrations(self._conn, "task_store")
        # Warm the in-memory cache from existing rows
        for row in self._conn.execute(_SELECT_ALL_SQL).fetchall():
            task_id, description, status, created_at, started_at, completed_at, success_int, output_json, error, tenant_id = row
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
                tenant_id=tenant_id or "_system_",
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
                record.tenant_id,
            ),
        )
        self._conn.commit()

    @staticmethod
    def _split_scope_token(token: str) -> tuple[str, str | None]:
        """Split tenant token into base tenant and optional workspace token.

        Supported format: "<tenant>@@ws:<workspace-token>".
        """
        marker = "@@ws:"
        if marker not in token:
            return token, None
        base, workspace = token.split(marker, 1)
        return base or "_system_", workspace or None

    @classmethod
    def _tenant_matches(cls, record_tenant: str, tenant_filter: str) -> bool:
        """Match record tenant against either base-tenant or workspace-scoped filter."""
        filter_base, filter_workspace = cls._split_scope_token(tenant_filter)
        record_base, record_workspace = cls._split_scope_token(record_tenant)

        if filter_workspace is not None:
            return record_base == filter_base and record_workspace == filter_workspace

        return record_base == filter_base

    # ── Public interface ──────────────────────────────────────────────────────

    def create(self, task: Task, tenant_id: str = "_system_") -> TaskRecord:
        record = TaskRecord(
            task_id=task.id,
            description=task.description,
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
            tenant_id=tenant_id,
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

    def list(self, tenant_id: str | None = None) -> list[TaskRecord]:
        """Return records, optionally filtered to a single tenant.

        When *tenant_id* is ``None`` or ``'_system_'``, all records are returned
        (single-user / config-key mode).  For any other tenant only that
        tenant's records are returned.
        """
        records = self._records.values()
        if tenant_id and tenant_id != "_system_":
            records = (r for r in records if self._tenant_matches(r.tenant_id, tenant_id))  # type: ignore[assignment]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def get(self, task_id: str, tenant_id: str | None = None) -> TaskRecord | None:
        """Return a record by task_id, optionally checking tenant ownership.

        Returns ``None`` (caller should return 404/403) if the record belongs to
        a different tenant when *tenant_id* is provided and not ``'_system_'``.
        """
        record = self._records.get(task_id)
        if record is None:
            return None
        if tenant_id and tenant_id != "_system_" and not self._tenant_matches(record.tenant_id, tenant_id):
            return None  # Treat as not found — don't leak existence
        return record

    def delete(self, task_id: str, tenant_id: str | None = None) -> bool:
        """Permanently remove a task record.

        Returns ``True`` if the record existed and was deleted, ``False`` otherwise.
        When *tenant_id* is provided (non-system), only deletes if it belongs to
        that tenant.
        """
        record = self._records.get(task_id)
        if record is None:
            return False
        if tenant_id and tenant_id != "_system_" and not self._tenant_matches(record.tenant_id, tenant_id):
            return False  # Treat as not found — don't leak existence
        del self._records[task_id]
        if self._conn is not None:
            self._conn.execute("DELETE FROM harness_tasks WHERE task_id = ?", (task_id,))
            self._conn.commit()
        return True

    def delete_many(self, tenant_id: str | None = None) -> int:
        """Delete all tasks matching the provided tenant filter.

        Returns the number of deleted records.
        """
        if tenant_id and tenant_id != "_system_":
            task_ids = [record.task_id for record in self._records.values() if self._tenant_matches(record.tenant_id, tenant_id)]
        else:
            task_ids = list(self._records.keys())

        if not task_ids:
            return 0

        for task_id in task_ids:
            self._records.pop(task_id, None)

        if self._conn is not None:
            placeholders = ",".join("?" for _ in task_ids)
            self._conn.execute(f"DELETE FROM harness_tasks WHERE task_id IN ({placeholders})", task_ids)
            self._conn.commit()

        return len(task_ids)
