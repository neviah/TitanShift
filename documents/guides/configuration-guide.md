# TitanShift Configuration Guide

This guide explains where config comes from, which values win, and which keys matter most in daily use.

## Config files

TitanShift reads configuration from:

1. harness/config_defaults.json (built-in defaults)
2. harness.config.json (project config)
3. harness.config.local.json (local override, optional)

Runtime overrides can also be set in-process by code paths that call ConfigManager.set.

## Precedence order

For a key such as orchestrator.workflow_mode, precedence is:

1. Environment variable HARNESS_ORCHESTRATOR_WORKFLOW_MODE
2. Runtime override set by ConfigManager.set
3. Merged file value from harness.config.local.json over harness.config.json
4. Built-in default in harness/config_defaults.json
5. Fallback default passed by caller

Notes:

- Local config overlays base config and wins when both define the same key.
- ConfigManager.set persists only to harness.config.json, not harness.config.local.json.
- Environment variable values are read as strings.

## Key sections

### api

- api.require_api_key
- api.api_key
- api.require_admin_api_key
- api.admin_api_key

Use local config for secrets in development.

### orchestrator

- orchestrator.workflow_mode
- orchestrator.enable_subagents
- orchestrator.lightning_mode.default_budget.max_steps
- orchestrator.lightning_mode.default_budget.max_tokens
- orchestrator.lightning_mode.default_budget.max_duration_ms
- orchestrator.superpowered_mode.disable_run_timeout
- orchestrator.superpowered_mode.run_timeout_seconds
- orchestrator.superpowered_mode.disable_budget_timeout
- orchestrator.superpowered_mode.require_task_reviews
- orchestrator.superpowered_mode.require_verification_before_done

Superpowered phase sequence enforcement:

- Spec and plan approvals are always required.
- Plan phase always runs before implementation in superpowered mode.
- There is no skip setting for these phases.

### model

- model.default_backend
- model.allow_cloud_adapters
- model.lmstudio.*
- model.openai_compatible.*

### execution

- execution.run_timeout_seconds
- execution.max_concurrent_runs
- execution.max_output_bytes
- execution.allowed_command_prefixes

### tools

- tools.deny_all_by_default
- tools.allow_network
- tools.allowed_paths
- tools.allowed_tool_names
- tools.blocked_tool_names
- tools.allowed_command_prefixes

### memory

- memory.semantic_backend
- memory.graph_backend
- memory.enable_chroma
- memory.storage_dir

## Environment variable mapping

Any dotted key can be mapped to an env var with this pattern:

- Prefix with HARNESS_
- Uppercase
- Replace dots with underscores

Examples:

- orchestrator.workflow_mode -> HARNESS_ORCHESTRATOR_WORKFLOW_MODE
- api.require_api_key -> HARNESS_API_REQUIRE_API_KEY

## Safe editing workflow

1. Start from harness.config.local.example.json for local-only values.
2. Keep shared defaults in harness.config.json.
3. Use local overrides for machine-specific keys and secrets.
4. Validate behavior by running a focused smoke test after edits.
