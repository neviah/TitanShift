"""SQLite-backed API key store.

Manages named, scoped API keys with expiry, revocation, and an audit event log.
Config-level keys (api.api_key / api.admin_api_key) remain the primary
authentication path and are not stored here; the key store supplements them
with individually manageable keys.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from harness.migrations.runner import apply_migrations, check_version

_KEY_PREFIX = "ts_"
_PREFIX_DISPLAY_LEN = 12  # "ts_" + 9 chars shown to operators


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Valid key scopes / roles (coarsest → finest privilege)
_VALID_SCOPES = frozenset({"read", "read_only", "operator", "admin"})
# Scopes that include write-level access
_OPERATOR_SCOPES = frozenset({"operator", "admin"})
# Scopes that include admin-level access
_ADMIN_SCOPES = frozenset({"admin"})


@dataclass
class KeyRecord:
    id: str
    description: str
    scope: str
    key_prefix: str
    key_hash: str
    created_at: str
    last_used_at: Optional[str]
    expires_at: Optional[str]
    revoked_at: Optional[str]
    # Multi-tenant fields (migration 002)
    tenant_id: str = "_system_"
    allowed_tools: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.allowed_tools is None:
            self.allowed_tools = []

    @property
    def is_active(self) -> bool:
        if self.revoked_at:
            return False
        if self.expires_at:
            exp = datetime.fromisoformat(self.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                return False
        return True

    @property
    def is_operator(self) -> bool:
        return self.scope in _OPERATOR_SCOPES

    @property
    def is_admin(self) -> bool:
        return self.scope in _ADMIN_SCOPES


@dataclass
class KeyEvent:
    id: int
    key_id: str
    event_type: str
    occurred_at: str
    metadata: dict


_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id          TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    scope       TEXT NOT NULL,
    key_hash    TEXT NOT NULL UNIQUE,
    key_prefix  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_used_at TEXT,
    expires_at  TEXT,
    revoked_at  TEXT
);

CREATE TABLE IF NOT EXISTS api_key_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id       TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    occurred_at  TEXT NOT NULL,
    metadata     TEXT NOT NULL DEFAULT '{}'
);
"""


class KeyStore:
    """Thread-safe SQLite-backed API key management store."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                check_version(conn, "key_store")
                apply_migrations(conn, "key_store")
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> KeyRecord:
        keys = row.keys()
        return KeyRecord(
            id=row["id"],
            description=row["description"],
            scope=row["scope"],
            key_prefix=row["key_prefix"],
            key_hash=row["key_hash"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
            tenant_id=row["tenant_id"] if "tenant_id" in keys else "_system_",
            allowed_tools=json.loads(row["allowed_tools"] or "[]") if "allowed_tools" in keys else [],
        )

    # ------------------------------------------------------------------
    # Key lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def generate_raw_key() -> str:
        """Return a new unique key string. Call this outside a lock."""
        return _KEY_PREFIX + secrets.token_urlsafe(32)

    def create_key(
        self,
        description: str,
        scope: str,
        expires_at: str | None = None,
        tenant_id: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> tuple[KeyRecord, str]:
        """Create and persist a new key.

        Returns ``(record, raw_key)``. The caller must surface ``raw_key``
        to the operator exactly once; it is never recoverable after this call.
        """
        if scope not in _VALID_SCOPES:
            raise ValueError(f"scope must be one of {sorted(_VALID_SCOPES)}, got {scope!r}")

        raw_key = self.generate_raw_key()
        key_id = str(uuid.uuid4())
        key_hash = _hash_key(raw_key)
        key_prefix = raw_key[:_PREFIX_DISPLAY_LEN]
        now = _now_iso()
        # Tenant defaults to the key's own ID so every key is isolated by default.
        effective_tenant = tenant_id if tenant_id else key_id
        allowed_tools_json = json.dumps(allowed_tools or [])

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO api_keys"
                    " (id, description, scope, key_hash, key_prefix, created_at,"
                    "  last_used_at, expires_at, revoked_at, tenant_id, allowed_tools)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (key_id, description, scope, key_hash, key_prefix,
                     now, None, expires_at, None, effective_tenant, allowed_tools_json),
                )
                conn.execute(
                    "INSERT INTO api_key_events (key_id, event_type, occurred_at, metadata)"
                    " VALUES (?,?,?,?)",
                    (key_id, "created", now, "{}"),
                )
                conn.commit()
            finally:
                conn.close()

        record = KeyRecord(
            id=key_id,
            description=description,
            scope=scope,
            key_prefix=key_prefix,
            key_hash=key_hash,
            created_at=now,
            last_used_at=None,
            expires_at=expires_at,
            revoked_at=None,
            tenant_id=effective_tenant,
            allowed_tools=allowed_tools or [],
        )
        return record, raw_key

    def list_keys(self) -> list[KeyRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM api_keys ORDER BY created_at DESC"
                ).fetchall()
                return [self._row_to_record(r) for r in rows]
            finally:
                conn.close()

    def get_key(self, key_id: str) -> KeyRecord | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM api_keys WHERE id = ?", (key_id,)
                ).fetchone()
                return self._row_to_record(row) if row else None
            finally:
                conn.close()

    def revoke_key(self, key_id: str) -> bool:
        """Mark a key as revoked. Returns False if already revoked or not found."""
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE api_keys SET revoked_at = ?"
                    " WHERE id = ? AND revoked_at IS NULL",
                    (now, key_id),
                )
                if cur.rowcount == 0:
                    return False
                conn.execute(
                    "INSERT INTO api_key_events (key_id, event_type, occurred_at, metadata)"
                    " VALUES (?,?,?,?)",
                    (key_id, "revoked", now, "{}"),
                )
                conn.commit()
                return True
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, raw_key: str) -> KeyRecord | None:
        """Verify a raw key against the store.

        Returns the active KeyRecord on success, ``None`` otherwise.
        Updates ``last_used_at`` and appends a ``used`` audit event on success.
        """
        key_hash = _hash_key(raw_key)
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
                ).fetchone()
                if not row:
                    return None
                record = self._row_to_record(row)
                if not record.is_active:
                    return None
                conn.execute(
                    "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                    (now, record.id),
                )
                conn.execute(
                    "INSERT INTO api_key_events (key_id, event_type, occurred_at, metadata)"
                    " VALUES (?,?,?,?)",
                    (record.id, "used", now, "{}"),
                )
                conn.commit()
                return record
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def get_events(self, key_id: str, limit: int = 50) -> list[KeyEvent]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM api_key_events"
                    " WHERE key_id = ? ORDER BY id DESC LIMIT ?",
                    (key_id, limit),
                ).fetchall()
                return [
                    KeyEvent(
                        id=row["id"],
                        key_id=row["key_id"],
                        event_type=row["event_type"],
                        occurred_at=row["occurred_at"],
                        metadata=json.loads(row["metadata"] or "{}"),
                    )
                    for row in rows
                ]
            finally:
                conn.close()
