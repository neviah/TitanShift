-- Migration 001: initial schema for harness_tasks table
-- Applied automatically by harness.migrations.runner

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
);
