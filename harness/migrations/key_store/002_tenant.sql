-- Migration 002: add tenant_id and allowed_tools columns to api_keys

ALTER TABLE api_keys ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '_system_';
ALTER TABLE api_keys ADD COLUMN allowed_tools TEXT NOT NULL DEFAULT '[]';
