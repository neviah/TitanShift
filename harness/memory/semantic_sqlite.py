from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from harness.migrations.runner import apply_migrations, check_version

# Thread-local storage for per-thread SQLite connections (WAL mode).
_local = threading.local()


class SemanticSQLiteStore:
    """SQLite FTS plus embeddings table default backend.

    Uses WAL journal mode and thread-local connections so concurrent reads
    from multiple threads do not serialize on a single connection lock.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Return the thread-local connection, creating it if needed."""
        conn = getattr(_local, "conn", None)
        if conn is None or getattr(_local, "db_path", None) != str(self.db_path):
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            # WAL mode: readers never block writers and vice-versa
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _local.conn = conn
            _local.db_path = str(self.db_path)
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        check_version(conn, "semantic_store")
        apply_migrations(conn, "semantic_store")
        conn.commit()

    def embed_and_store(self, doc_id: str, text: str, metadata: dict[str, Any], embedding: list[float]) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO semantic_docs(doc_id, content, metadata) VALUES (?, ?, ?)",
            (doc_id, text, json.dumps(metadata)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO semantic_embeddings(doc_id, embedding_json) VALUES (?, ?)",
            (doc_id, json.dumps(embedding)),
        )
        conn.commit()

    def semantic_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT doc_id, content, metadata FROM semantic_docs WHERE semantic_docs MATCH ? LIMIT ?",
            (query, limit),
        ).fetchall()
        return [{"doc_id": r[0], "content": r[1], "metadata": json.loads(r[2])} for r in rows]
