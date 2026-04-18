"""Migration runner for SQLite-backed harness stores.

Maintains a ``_schema_migrations`` table in each database that tracks which
numbered migrations have been applied.  Migrations are plain SQL files named
``{NNN}_{description}.sql`` under ``harness/migrations/{db_name}/``.

The runner is idempotent: running it twice applies nothing on the second call.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence


# Root directory that contains per-database migration subdirectories.
_MIGRATIONS_ROOT = Path(__file__).resolve().parent

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS _schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""


class MigrationError(RuntimeError):
    """Raised when the on-disk schema is ahead of available migrations."""


def _collect_migrations(db_name: str) -> list[tuple[int, str, Path]]:
    """Return sorted list of (version, name, path) for the given db namespace."""
    migration_dir = _MIGRATIONS_ROOT / db_name
    if not migration_dir.is_dir():
        return []
    results: list[tuple[int, str, Path]] = []
    for f in sorted(migration_dir.glob("*.sql")):
        stem = f.stem  # e.g. "001_initial"
        parts = stem.split("_", 1)
        try:
            version = int(parts[0])
        except ValueError:
            continue
        name = parts[1] if len(parts) > 1 else stem
        results.append((version, name, f))
    return results


def current_version(conn: sqlite3.Connection) -> int:
    """Return the highest migration version applied to this connection, or 0."""
    conn.execute(_CREATE_MIGRATIONS_TABLE)
    row = conn.execute("SELECT MAX(version) FROM _schema_migrations").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def apply_migrations(conn: sqlite3.Connection, db_name: str) -> list[int]:
    """Apply all pending migrations for *db_name* to *conn*.

    Returns the list of version numbers that were applied in this call.
    Raises ``MigrationError`` if the DB is already at a higher version than any
    known migration file (schema was created by a newer binary).
    """
    conn.execute(_CREATE_MIGRATIONS_TABLE)
    conn.commit()

    available = _collect_migrations(db_name)
    applied_versions: set[int] = {
        row[0] for row in conn.execute("SELECT version FROM _schema_migrations").fetchall()
    }
    newly_applied: list[int] = []

    if available:
        max_available = max(v for v, _, _ in available)
        max_applied = max(applied_versions) if applied_versions else 0
        if max_applied > max_available:
            raise MigrationError(
                f"Database '{db_name}' is at schema version {max_applied} but the "
                f"highest known migration is {max_available}. "
                "Downgrade is not supported. Use a binary that matches this schema version."
            )

    for version, name, path in available:
        if version in applied_versions:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO _schema_migrations (version, name) VALUES (?, ?)",
            (version, name),
        )
        conn.commit()
        newly_applied.append(version)

    return newly_applied


def check_version(conn: sqlite3.Connection, db_name: str) -> None:
    """Assert the DB is not ahead of known migrations.  Call at startup."""
    available = _collect_migrations(db_name)
    if not available:
        return
    max_available = max(v for v, _, _ in available)

    conn.execute(_CREATE_MIGRATIONS_TABLE)
    conn.commit()
    row = conn.execute("SELECT MAX(version) FROM _schema_migrations").fetchone()
    max_applied = int(row[0]) if row and row[0] is not None else 0

    if max_applied > max_available:
        raise MigrationError(
            f"[{db_name}] schema version {max_applied} is newer than the highest "
            f"known migration ({max_available}). "
            "Please upgrade the harness package or run with a compatible binary."
        )
