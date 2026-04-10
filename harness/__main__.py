from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

import uvicorn

from harness.api.server import create_app
from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry
from harness.orchestrator.orchestrator import Orchestrator
from harness.runtime.config import ConfigManager
from harness.runtime.event_bus import EventBus
from harness.runtime.types import Task
from harness.tools.registry import PermissionPolicy, ToolRegistry


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

    serve_api = sub.add_parser("serve-api", help="Run FastAPI server")
    serve_api.add_argument("--host", default="127.0.0.1")
    serve_api.add_argument("--port", type=int, default=8000)

    sub.add_parser("status", help="Show current runtime status")
    sub.add_parser("print-config", help="Print resolved defaults from config files")
    return parser


async def run_task(prompt: str, workspace_root: Path, backend: str | None = None) -> None:
    cfg = ConfigManager(workspace_root)
    bus = EventBus()
    memory = MemoryManager(cfg, workspace_root)
    models = ModelRegistry.from_config(cfg)
    tools = ToolRegistry(PermissionPolicy.from_config(cfg, workspace_root))
    orchestrator = Orchestrator(config=cfg, event_bus=bus, memory=memory, models=models, tools=tools)

    task_input = {"model_backend": backend} if backend else {}
    task = Task(id=str(uuid.uuid4()), description=prompt, input=task_input)
    result = await orchestrator.run_reactive_task(task)
    print(json.dumps(result.output, indent=2))


def print_status(workspace_root: Path) -> None:
    cfg = ConfigManager(workspace_root)
    print("Harness status")
    print(f"- workspace: {workspace_root}")
    print(f"- subagents enabled: {cfg.get('orchestrator.enable_subagents')}")
    print(f"- graph backend: {cfg.get('memory.graph_backend')}")
    print(f"- semantic backend: {cfg.get('memory.semantic_backend')}")
    print(f"- chroma enabled: {cfg.get('memory.enable_chroma')}")
    print(f"- graphify plugin enabled: {cfg.get('ingestion.enable_graphify_plugin')}")


def print_config(workspace_root: Path) -> None:
    defaults_path = workspace_root / "harness" / "config_defaults.json"
    if defaults_path.exists():
        print(defaults_path.read_text(encoding="utf-8"))
    else:
        print("No defaults file found.")


def serve_api(workspace_root: Path, host: str, port: int) -> None:
    app = create_app(workspace_root)
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    workspace_root = Path(args.workspace).resolve()

    if args.command == "run-task":
        asyncio.run(run_task(args.prompt, workspace_root, args.backend))
    elif args.command == "status":
        print_status(workspace_root)
    elif args.command == "print-config":
        print_config(workspace_root)
    elif args.command == "serve-api":
        serve_api(workspace_root, args.host, args.port)


if __name__ == "__main__":
    main()
