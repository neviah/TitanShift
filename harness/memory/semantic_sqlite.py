from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from harness.migrations.runner import apply_migrations, check_version


class SemanticSQLiteStore:
    """SQLite FTS plus embeddings table default backend."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            check_version(conn, "semantic_store")
            apply_migrations(conn, "semantic_store")

    def embed_and_store(self, doc_id: str, text: str, metadata: dict[str, Any], embedding: list[float]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO semantic_docs(doc_id, content, metadata) VALUES (?, ?, ?)",
                (doc_id, text, json.dumps(metadata)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO semantic_embeddings(doc_id, embedding_json) VALUES (?, ?)",
                (doc_id, json.dumps(embedding)),
            )

    def semantic_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT doc_id, content, metadata FROM semantic_docs WHERE semantic_docs MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
        return [{"doc_id": r[0], "content": r[1], "metadata": json.loads(r[2])} for r in rows]
