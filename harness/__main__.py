from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

import uvicorn

from harness.api.server import create_app
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


if __name__ == "__main__":
    main()
