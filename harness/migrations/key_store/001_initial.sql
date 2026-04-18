-- Migration 001: initial schema for API key store
-- Applied automatically by harness.migrations.runner

CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    description  TEXT NOT NULL DEFAULT '',
    scope        TEXT NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    key_prefix   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    expires_at   TEXT,
    revoked_at   TEXT
);

CREATE TABLE IF NOT EXISTS api_key_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    occurred_at TEXT    NOT NULL,
    metadata    TEXT    NOT NULL DEFAULT '{}'
);
