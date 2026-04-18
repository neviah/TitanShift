-- Migration 001: initial schema for semantic SQLite memory store
-- Applied automatically by harness.migrations.runner

CREATE VIRTUAL TABLE IF NOT EXISTS semantic_docs USING fts5(doc_id, content, metadata);

CREATE TABLE IF NOT EXISTS semantic_embeddings (
    doc_id         TEXT PRIMARY KEY,
    embedding_json TEXT NOT NULL
);
