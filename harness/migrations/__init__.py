"""Incremental SQLite schema migration system.

Usage from any SQLite-backed store:

    from harness.migrations.runner import apply_migrations
    apply_migrations(conn, db_name="task_store")

Each database has its own namespace so version numbers don't collide.
Migration SQL files live under ``harness/migrations/{db_name}/``.
"""
