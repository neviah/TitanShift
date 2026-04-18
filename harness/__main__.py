from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import uvicorn

from harness.api.server import create_app
from harness.migrations.runner import MigrationError, apply_migrations, check_version
from harness.model.adapter import check_lmstudio_health
from harness.runtime.bootstrap import build_runtime
from harness.runtime.config import ConfigManager
from harness.runtime.types import Task


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Universal Harness CLI")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run-task", help="Run a single reactive task")
    run_cmd.add_argument("prompt", help="Task prompt")
    run_cmd.add_argument(
        "--backend",
        choices=["local_stub", "lmstudio", "openai_compatible"],
        default=None,
        help="Optional model backend override",
    )

    run_tool_cmd = sub.add_parser("run-tool", help="Run a registered tool with JSON args")
    run_tool_cmd.add_argument("name", help="Tool name")
    run_tool_cmd.add_argument("--args", default="{}", help="JSON args object")
    run_tool_cmd.add_argument(
        "--command",
        dest="tool_command",
        default=None,
        help="Shortcut: sets args.command for shell_command",
    )

    serve_api = sub.add_parser("serve-api", help="Run FastAPI server")
    serve_api.add_argument("--host", default="127.0.0.1")
    serve_api.add_argument("--port", type=int, default=8000)

    sub.add_parser("lmstudio-check", help="Validate LM Studio endpoint, model, and tiny inference")

    sub.add_parser("status", help="Show current runtime status")
    sub.add_parser("print-config", help="Print resolved defaults from config files")

    # ── Migration commands ────────────────────────────────────────────────────
    sub.add_parser(
        "migrate",
        help="Apply any pending schema migrations to all SQLite databases",
    )

    config_cmd = sub.add_parser("config", help="Configuration utilities")
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser(
        "migrate",
        help="Compare the on-disk harness.config.json against current defaults and show diffs",
    )

    return parser


async def run_task(prompt: str, workspace_root: Path, backend: str | None = None) -> None:
    runtime = build_runtime(workspace_root)

    task_input = {"model_backend": backend} if backend else {}
    task = Task(id=str(uuid.uuid4()), description=prompt, input=task_input)
    result = await runtime.orchestrator.run_reactive_task(task)
    print(json.dumps(result.output, indent=2))


async def run_tool(name: str, raw_args: str, workspace_root: Path, command: str | None = None) -> None:
    runtime = build_runtime(workspace_root)
    try:
        if command is not None:
            args = {"command": command}
        else:
            args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"Invalid JSON for --args: {exc}"}, indent=2))
        return

    try:
        result = await runtime.tools.execute_tool(name, args)
        print(json.dumps(result, indent=2))
    except (KeyError, PermissionError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))


def print_status(workspace_root: Path) -> None:
    runtime = build_runtime(workspace_root)
    cfg = runtime.config
    print("Harness status")
    print(f"- workspace: {workspace_root}")
    print(f"- subagents enabled: {cfg.get('orchestrator.enable_subagents')}")
    print(f"- graph backend: {cfg.get('memory.graph_backend')}")
    print(f"- semantic backend: {cfg.get('memory.semantic_backend')}")
    print(f"- chroma enabled: {cfg.get('memory.enable_chroma')}")
    print(f"- graphify plugin enabled: {cfg.get('ingestion.enable_graphify_plugin')}")
    print(f"- loaded modules: {runtime.module_loader.list_modules()}")


def print_config(workspace_root: Path) -> None:
    defaults_path = workspace_root / "harness" / "config_defaults.json"
    if defaults_path.exists():
        print(defaults_path.read_text(encoding="utf-8"))
    else:
        print("No defaults file found.")


# ── Migration helpers ─────────────────────────────────────────────────────────

_DB_NAMES: list[tuple[str, str]] = [
    ("task_store",    "harness_data/tasks.db"),
    ("semantic_store", "harness_data/semantic.db"),
    ("key_store",     "harness_data/key_store.db"),
]


def run_migrate(workspace_root: Path) -> None:
    """Apply pending migrations to all known SQLite databases."""
    any_applied = False
    for db_name, rel_path in _DB_NAMES:
        db_path = workspace_root / rel_path
        if not db_path.exists():
            print(f"  [skip] {db_name}: database not found at {rel_path}")
            continue
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            check_version(conn, db_name)
            applied = apply_migrations(conn, db_name)
            if applied:
                print(f"  [ok]   {db_name}: applied migrations {applied}")
                any_applied = True
            else:
                print(f"  [ok]   {db_name}: already up to date")
        except MigrationError as exc:
            print(f"  [ERROR] {db_name}: {exc}")
            raise SystemExit(1) from exc
        finally:
            conn.close()
    if not any_applied:
        print("All databases are up to date.")


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict into dotted keys."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, full_key))
        else:
            out[full_key] = v
    return out


def run_config_migrate(workspace_root: Path) -> None:
    """Compare on-disk config against current defaults and report differences."""
    defaults_path = workspace_root / "harness" / "config_defaults.json"
    config_path = workspace_root / "harness.config.json"

    defaults: dict[str, Any] = {}
    if defaults_path.exists():
        defaults = json.loads(defaults_path.read_text(encoding="utf-8"))

    file_cfg: dict[str, Any] = {}
    if config_path.exists():
        file_cfg = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        print("No harness.config.json found — nothing to migrate.")
        return

    flat_defaults = _flatten(defaults)
    flat_file = _flatten(file_cfg)

    missing_keys = [k for k in flat_defaults if k not in flat_file]
    extra_keys = [k for k in flat_file if k not in flat_defaults]
    changed: list[tuple[str, Any, Any]] = [
        (k, flat_file[k], flat_defaults[k])
        for k in flat_file
        if k in flat_defaults and flat_file[k] != flat_defaults[k]
    ]

    deprecated_map: dict[str, str] = {
        # Add deprecated → current key renames here, e.g.:
        # "old.key": "new.key",
    }
    deprecated_used = [(old, new) for old, new in deprecated_map.items() if old in flat_file]

    print("=== Config migration report ===")
    if missing_keys:
        print(f"\n  Keys present in defaults but missing from your config ({len(missing_keys)}):")
        for k in sorted(missing_keys):
            print(f"    + {k}  (default: {flat_defaults[k]!r})")
    if extra_keys:
        print(f"\n  Keys in your config not present in defaults ({len(extra_keys)}) — may be custom or legacy:")
        for k in sorted(extra_keys):
            print(f"    ? {k}  =  {flat_file[k]!r}")
    if changed:
        print(f"\n  Keys that differ from defaults ({len(changed)}):")
        for k, yours, theirs in sorted(changed):
            print(f"    ~ {k}  yours={yours!r}  default={theirs!r}")
    if deprecated_used:
        print(f"\n  [WARN] Deprecated keys in use ({len(deprecated_used)}):")
        for old, new in deprecated_used:
            print(f"    DEPRECATED {old!r}  →  rename to {new!r}")
    if not any([missing_keys, extra_keys, changed, deprecated_used]):
        print("  Config is in sync with current defaults.")
    print()




def serve_api(workspace_root: Path, host: str, port: int) -> None:
    app = create_app(workspace_root)
    uvicorn.run(app, host=host, port=port)


def lmstudio_check(workspace_root: Path) -> None:
    cfg = ConfigManager(workspace_root)
    result = check_lmstudio_health(cfg)
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    workspace_root = Path(args.workspace).resolve()

    if args.command == "run-task":
        asyncio.run(run_task(args.prompt, workspace_root, args.backend))
    elif args.command == "run-tool":
        asyncio.run(run_tool(args.name, args.args, workspace_root, args.tool_command))
    elif args.command == "status":
        print_status(workspace_root)
    elif args.command == "print-config":
        print_config(workspace_root)
    elif args.command == "serve-api":
        serve_api(workspace_root, args.host, args.port)
    elif args.command == "lmstudio-check":
        lmstudio_check(workspace_root)
    elif args.command == "migrate":
        run_migrate(workspace_root)
    elif args.command == "config":
        if args.config_command == "migrate":
            run_config_migrate(workspace_root)


if __name__ == "__main__":
    main()
