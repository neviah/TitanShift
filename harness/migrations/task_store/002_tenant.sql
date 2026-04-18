-- Migration 002: add tenant_id column to harness_tasks for per-tenant isolation

ALTER TABLE harness_tasks ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '_system_';
