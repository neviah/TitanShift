from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shlex
import hashlib
from html import escape
from datetime import datetime, timezone
from typing import Any

import httpx
import yaml

from harness.execution.runner import ExecutionDeniedError, ExecutionModule
from harness.tools.definitions import ToolDefinition
from harness.tools.registry import ToolRegistry


def register_builtin_tools(tools: ToolRegistry, execution: ExecutionModule) -> None:
    def _resolve_workspace_path(raw_path: str) -> Path:
        candidate = Path(raw_path)
        return candidate.resolve() if candidate.is_absolute() else (execution.default_cwd / candidate).resolve()

    def _rollback_scaffold_transaction(
        operations: list[dict[str, Any]],
        base_path: Path,
    ) -> None:
        for operation in reversed(operations):
            target = operation["target"]
            existed_before = bool(operation["existed_before"])
            if existed_before:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(operation["original_content"]), encoding="utf-8")
                continue

            if target.exists():
                target.unlink(missing_ok=True)

            parent = target.parent
            while parent != base_path and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent

    def _write_scaffold_files(base_path: Path, files: dict[str, str], overwrite: bool) -> dict[str, Any]:
        operations: list[dict[str, Any]] = []
        for relative_path, content in files.items():
            target = (base_path / relative_path).resolve()
            existed_before = target.exists()
            if existed_before and target.is_dir():
                raise ValueError(f"target file path points to a directory: {target}")
            if existed_before and not overwrite:
                raise ValueError(f"target file already exists and overwrite=false: {target}")
            operations.append(
                {
                    "target": target,
                    "content": content,
                    "existed_before": existed_before,
                    "original_content": target.read_text(encoding="utf-8", errors="replace") if existed_before else None,
                }
            )

        created_paths: list[str] = []
        updated_paths: list[str] = []
        applied_operations: list[dict[str, Any]] = []
        try:
            for operation in operations:
                target = operation["target"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(operation["content"]), encoding="utf-8")
                applied_operations.append(operation)
                normalized = str(target).replace("\\", "/")
                if bool(operation["existed_before"]):
                    updated_paths.append(normalized)
                else:
                    created_paths.append(normalized)
        except Exception:
            _rollback_scaffold_transaction(applied_operations, base_path)
            raise

        return {
            "created_paths": created_paths,
            "updated_paths": updated_paths,
            "operations": applied_operations,
        }

    async def _run_project_install(project_type: str, target: Path) -> dict[str, Any]:
        normalized_type = project_type.strip().lower()
        if normalized_type == "fastapi":
            command = "python"
            args = ["-m", "pip", "install", "-r", "requirements.txt"]
        elif normalized_type in {"vite", "react", "vite-react", "react-vite"}:
            command = "npm"
            args = ["install"]
        else:
            return {
                "ok": True,
                "skipped": True,
                "command": None,
                "stdout": "",
                "stderr": "",
                "returncode": 0,
                "truncated": False,
                "reason": "No dependency installation required for this project type.",
            }

        try:
            result = await execution.run_command(command, *args, cwd=str(target))
        except ExecutionDeniedError as exc:
            return {
                "ok": False,
                "skipped": False,
                "command": " ".join([command, *args]),
                "stdout": "",
                "stderr": str(exc),
                "returncode": -1,
                "truncated": False,
            }

        return {
            "ok": result.returncode == 0,
            "skipped": False,
            "command": " ".join([command, *args]),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "truncated": result.truncated,
        }

    def _parse_version_from_text(text: str) -> str | None:
        match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", text)
        return match.group(0) if match else None

    def _bump_semver(current: str, bump: str, set_version: str | None = None) -> str:
        if bump == "set":
            if not set_version or not re.fullmatch(r"\d+\.\d+\.\d+", set_version):
                raise ValueError("set_version must match semantic version format X.Y.Z")
            return set_version
        major, minor, patch = [int(v) for v in current.split(".")]
        if bump == "major":
            return f"{major + 1}.0.0"
        if bump == "minor":
            return f"{major}.{minor + 1}.0"
        if bump == "patch":
            return f"{major}.{minor}.{patch + 1}"
        raise ValueError("bump must be one of: patch, minor, major, set")

    def _release_category_for_commit(line: str) -> str:
        message = line.strip()
        if " " in message:
            message = message.split(" ", 1)[1].strip()
        lowered = message.lower()
        if re.match(r"^(feat|feature)(\(.+\))?:", lowered):
            return "features"
        if re.match(r"^fix(\(.+\))?:", lowered):
            return "fixes"
        if re.match(r"^chore(\(.+\))?:", lowered):
            return "chore"
        return "other"

    def _build_project_scaffold(project_type: str, project_name: str) -> tuple[dict[str, str], list[str], list[str]]:
        normalized_type = project_type.strip().lower()
        package_name = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-") or "app"
        module_name = re.sub(r"[^a-z0-9]+", "_", project_name.lower()).strip("_") or "app"

        if normalized_type == "fastapi":
            files = {
                "app/__init__.py": "",
                "app/main.py": (
                    "from fastapi import FastAPI\n\n"
                    f"app = FastAPI(title=\"{project_name}\")\n\n"
                    "@app.get(\"/\")\n"
                    "def read_root() -> dict[str, str]:\n"
                    f"    return {{\"message\": \"{project_name} is running\"}}\n"
                ),
                "requirements.txt": "fastapi>=0.116\nuvicorn>=0.35\n",
                "README.md": (
                    f"# {project_name}\n\n"
                    "## Run\n\n"
                    "```bash\n"
                    "python -m uvicorn app.main:app --reload\n"
                    "```\n"
                ),
            }
            commands = [
                "python -m pip install -r requirements.txt",
                "python -m uvicorn app.main:app --reload",
            ]
            notes = ["Generated a minimal FastAPI app scaffold."]
            return files, commands, notes

        if normalized_type in {"vite", "react", "vite-react", "react-vite"}:
            files = {
                "package.json": json.dumps(
                    {
                        "name": package_name,
                        "private": True,
                        "version": "0.1.0",
                        "type": "module",
                        "scripts": {
                            "dev": "vite",
                            "build": "vite build",
                            "preview": "vite preview",
                        },
                        "dependencies": {
                            "react": "^18.3.1",
                            "react-dom": "^18.3.1",
                        },
                        "devDependencies": {
                            "@vitejs/plugin-react": "^4.3.1",
                            "vite": "^5.4.10",
                        },
                    },
                    indent=2,
                )
                + "\n",
                "index.html": (
                    "<!doctype html>\n"
                    "<html lang=\"en\">\n"
                    "  <head>\n"
                    "    <meta charset=\"UTF-8\" />\n"
                    "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
                    f"    <title>{project_name}</title>\n"
                    "    <script type=\"module\" src=\"/src/main.jsx\"></script>\n"
                    "  </head>\n"
                    "  <body>\n"
                    "    <div id=\"root\"></div>\n"
                    "  </body>\n"
                    "</html>\n"
                ),
                "src/main.jsx": (
                    "import React from 'react'\n"
                    "import ReactDOM from 'react-dom/client'\n"
                    "import './styles.css'\n"
                    "import { App } from './App'\n\n"
                    "ReactDOM.createRoot(document.getElementById('root')).render(\n"
                    "  <React.StrictMode>\n"
                    "    <App />\n"
                    "  </React.StrictMode>,\n"
                    ")\n"
                ),
                "src/App.jsx": (
                    "export function App() {\n"
                    "  return (\n"
                    "    <main className=\"app-shell\">\n"
                    f"      <h1>{project_name}</h1>\n"
                    "      <p>Edit src/App.jsx to start building.</p>\n"
                    "    </main>\n"
                    "  )\n"
                    "}\n"
                ),
                "src/styles.css": (
                    ":root {\n"
                    "  font-family: Georgia, 'Times New Roman', serif;\n"
                    "  color: #1b1b1b;\n"
                    "  background: linear-gradient(135deg, #f5efe0 0%, #d8e2dc 100%);\n"
                    "}\n\n"
                    "body {\n"
                    "  margin: 0;\n"
                    "  min-height: 100vh;\n"
                    "}\n\n"
                    "#root {\n"
                    "  min-height: 100vh;\n"
                    "}\n\n"
                    ".app-shell {\n"
                    "  min-height: 100vh;\n"
                    "  display: grid;\n"
                    "  place-items: center;\n"
                    "  text-align: center;\n"
                    "  padding: 2rem;\n"
                    "}\n"
                ),
            }
            commands = ["npm install", "npm run dev"]
            notes = ["Generated a minimal Vite React scaffold."]
            return files, commands, notes

        if normalized_type in {"static", "static-site", "html"}:
            files = {
                "index.html": (
                    "<!doctype html>\n"
                    "<html lang=\"en\">\n"
                    "  <head>\n"
                    "    <meta charset=\"UTF-8\" />\n"
                    "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
                    f"    <title>{project_name}</title>\n"
                    "    <link rel=\"stylesheet\" href=\"styles.css\" />\n"
                    "  </head>\n"
                    "  <body>\n"
                    "    <main class=\"page\">\n"
                    f"      <h1>{project_name}</h1>\n"
                    "      <p>Your static site scaffold is ready.</p>\n"
                    "    </main>\n"
                    "  </body>\n"
                    "</html>\n"
                ),
                "styles.css": (
                    "body {\n"
                    "  margin: 0;\n"
                    "  min-height: 100vh;\n"
                    "  display: grid;\n"
                    "  place-items: center;\n"
                    "  background: linear-gradient(160deg, #e7ecef 0%, #d9cfc1 100%);\n"
                    "  color: #202124;\n"
                    "  font-family: 'Trebuchet MS', sans-serif;\n"
                    "}\n\n"
                    ".page {\n"
                    "  text-align: center;\n"
                    "  padding: 2rem;\n"
                    "}\n"
                ),
            }
            commands = ["python -m http.server 8000"]
            notes = ["Generated a minimal static site scaffold."]
            return files, commands, notes

        raise ValueError("project_type must be one of: fastapi, vite-react, static-site")

    def _normalize_component_name(raw_name: str) -> tuple[str, str]:
        words = [part for part in re.split(r"[^A-Za-z0-9]+", raw_name.strip()) if part]
        if not words:
            raise ValueError("name must contain at least one alphanumeric character")
        pascal_name = "".join(word[:1].upper() + word[1:] for word in words)
        kebab_name = "-".join(word.lower() for word in words)
        return pascal_name, kebab_name

    def _build_component_scaffold(
        framework: str,
        component_name: str,
        props_schema: dict[str, Any] | None,
    ) -> tuple[dict[str, str], list[str]]:
        normalized_framework = framework.strip().lower()
        pascal_name, kebab_name = _normalize_component_name(component_name)
        prop_names = list(props_schema.keys()) if isinstance(props_schema, dict) else []

        if normalized_framework in {"react", "vite-react", "react-vite"}:
            destructured_props = ", ".join(prop_names)
            prop_signature = f"{{ {destructured_props} }}" if destructured_props else "{}"
            details = "\n".join(
                f"      <p>{prop}: {{{prop}}}</p>" for prop in prop_names
            ) or "      <p>Replace this placeholder content with your UI.</p>"
            files = {
                f"src/components/{pascal_name}.jsx": (
                    f"export function {pascal_name}({prop_signature}) {{\n"
                    "  return (\n"
                    f"    <section className=\"component component-{kebab_name}\">\n"
                    f"      <h2>{pascal_name}</h2>\n"
                    f"{details}\n"
                    "    </section>\n"
                    "  )\n"
                    "}\n"
                ),
            }
            return files, [f"Generated React component {pascal_name} in src/components."]

        if normalized_framework in {"static", "static-site", "html"}:
            files = {
                f"components/{kebab_name}.html": (
                    f"<section class=\"component component-{kebab_name}\">\n"
                    f"  <h2>{pascal_name}</h2>\n"
                    "  <p>Replace this placeholder content with your markup.</p>\n"
                    "</section>\n"
                ),
            }
            return files, [f"Generated static HTML component snippet {kebab_name}.html."]

        raise ValueError("framework must be one of: vite-react, react, static-site")

    def _build_route_scaffold(
        framework: str,
        route_path: str,
        with_loader: bool,
        with_tests: bool,
    ) -> tuple[dict[str, str], list[str]]:
        normalized_framework = framework.strip().lower()
        cleaned_route = route_path.strip() or "/"
        cleaned_route = cleaned_route if cleaned_route.startswith("/") else f"/{cleaned_route}"
        route_parts = [part for part in cleaned_route.strip("/").split("/") if part]
        if not route_parts:
            route_parts = ["home"]
        pascal_name = "".join(part[:1].upper() + part[1:] for part in route_parts) + "Route"
        kebab_name = "-".join(route_parts)

        if normalized_framework in {"react", "vite-react", "react-vite"}:
            loader_block = (
                "export async function loader() {\n"
                f"  return {{ route: '{cleaned_route}' }}\n"
                "}\n\n"
            ) if with_loader else ""
            files = {
                f"src/routes/{pascal_name}.jsx": (
                    f"{loader_block}export function {pascal_name}() {{\n"
                    "  return (\n"
                    f"    <section className=\"route route-{kebab_name}\">\n"
                    f"      <h1>{pascal_name}</h1>\n"
                    f"      <p>Route path: {cleaned_route}</p>\n"
                    "    </section>\n"
                    "  )\n"
                    "}\n"
                ),
            }
            if with_tests:
                files[f"src/routes/{pascal_name}.test.jsx"] = (
                    f"import {{ {pascal_name} }} from './{pascal_name}'\n\n"
                    f"describe('{pascal_name}', () => {{\n"
                    "  it('is defined', () => {\n"
                    f"    expect({pascal_name}).toBeDefined()\n"
                    "  })\n"
                    "})\n"
                )
            return files, [f"Generated React route {pascal_name} for path {cleaned_route}."]

        if normalized_framework == "fastapi":
            module_name = "_".join(route_parts)
            files = {
                f"app/routes/{module_name}.py": (
                    "from fastapi import APIRouter\n\n"
                    f"router = APIRouter(prefix='{cleaned_route}', tags=['{module_name}'])\n\n"
                    "@router.get('/')\n"
                    "def read_route() -> dict[str, str]:\n"
                    f"    return {{'route': '{cleaned_route}'}}\n"
                ),
            }
            if with_tests:
                files[f"tests/test_{module_name}_route.py"] = (
                    "from app.routes import " + module_name + "\n\n"
                    "def test_router_exists() -> None:\n"
                    f"    assert {module_name}.router is not None\n"
                )
            return files, [f"Generated FastAPI route module for path {cleaned_route}."]

        if normalized_framework in {"static", "static-site", "html"}:
            files = {
                f"routes/{kebab_name}.html": (
                    "<!doctype html>\n"
                    "<html lang=\"en\">\n"
                    "  <head><meta charset=\"UTF-8\" /><title>"
                    + pascal_name
                    + "</title></head>\n"
                    "  <body>\n"
                    f"    <main><h1>{pascal_name}</h1><p>Route path: {cleaned_route}</p></main>\n"
                    "  </body>\n"
                    "</html>\n"
                ),
            }
            return files, [f"Generated static route page for path {cleaned_route}."]

        raise ValueError("framework must be one of: vite-react, react, fastapi, static-site")

    async def shell_command_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw = str(args.get("command", "")).strip()
        if not raw:
            raise ValueError("command is required")

        parts = shlex.split(raw, posix=False)
        command = parts[0]
        command_args = [str(p) for p in parts[1:]]
        try:
            result = await execution.run_command(command, *command_args, cwd=args.get("cwd"))
        except ExecutionDeniedError as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
        }

    tools.register_tool(
        ToolDefinition(
            name="shell_command",
            description="Run a shell command through the policy-constrained execution module.",
            handler=shell_command_handler,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"},
                    "cwd": {"type": "string", "description": "Optional working directory"},
                },
                "required": ["command"],
            },
        )
    )

    async def create_directory_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("directory_path") or args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("directory_path is required")
        target = _resolve_workspace_path(raw_path)
        target.mkdir(parents=True, exist_ok=True)
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "created": True,
        }

    tools.register_tool(
        ToolDefinition(
            name="create_directory",
            description="Create a directory inside the allowed workspace. Use this before writing multiple related files or scaffolding a small app.",
            handler=create_directory_handler,
            parameters={
                "type": "object",
                "properties": {
                    "directory_path": {"type": "string", "description": "Directory path relative to workspace root or absolute allowed path"},
                },
                "required": ["directory_path"],
            },
        )
    )

    async def init_project_handler(args: dict[str, Any]) -> dict[str, Any]:
        project_type = str(args.get("project_type") or "").strip()
        project_name = str(args.get("name") or "").strip()
        raw_target_path = str(args.get("target_path") or args.get("path") or "").strip()
        overwrite = bool(args.get("overwrite", False))
        install_dependencies = bool(args.get("install_dependencies", False))

        if not project_type:
            raise ValueError("project_type is required")
        if not project_name:
            raise ValueError("name is required")
        if not raw_target_path:
            raise ValueError("target_path is required")

        target = _resolve_workspace_path(raw_target_path)
        target.mkdir(parents=True, exist_ok=True)

        files, commands_to_run, notes = _build_project_scaffold(project_type, project_name)
        transaction = _write_scaffold_files(target, files, overwrite)
        install_result = None
        rolled_back = False
        if install_dependencies:
            install_result = await _run_project_install(project_type, target)
            if not bool(install_result.get("ok", False)):
                _rollback_scaffold_transaction(list(transaction["operations"]), target)
                rolled_back = True
                return {
                    "ok": False,
                    "project_type": project_type,
                    "name": project_name,
                    "target_path": str(target).replace("\\", "/"),
                    "created_paths": [],
                    "updated_paths": [],
                    "commands_to_run": commands_to_run,
                    "install_result": install_result,
                    "rolled_back": True,
                    "notes": notes + ["Rolled back scaffold because dependency installation failed."],
                }

        return {
            "ok": True,
            "project_type": project_type,
            "name": project_name,
            "target_path": str(target).replace("\\", "/"),
            "created_paths": transaction["created_paths"],
            "updated_paths": transaction["updated_paths"],
            "commands_to_run": commands_to_run,
            "install_result": install_result,
            "rolled_back": rolled_back,
            "notes": notes,
        }

    tools.register_tool(
        ToolDefinition(
            name="init_project",
            description="Scaffold a minimal starter project for fastapi, vite-react, or static-site projects.",
            handler=init_project_handler,
            parameters={
                "type": "object",
                "properties": {
                    "project_type": {"type": "string", "description": "fastapi | vite-react | static-site"},
                    "name": {"type": "string", "description": "Display name for the generated project"},
                    "target_path": {"type": "string", "description": "Directory to scaffold into, relative to workspace root or absolute allowed path"},
                    "install_dependencies": {"type": "boolean", "description": "Whether to run npm install or pip install -r requirements.txt when applicable"},
                    "overwrite": {"type": "boolean", "description": "Whether existing scaffold files may be replaced; defaults to false"},
                },
                "required": ["project_type", "name", "target_path"],
            },
        )
    )

    async def generate_component_handler(args: dict[str, Any]) -> dict[str, Any]:
        framework = str(args.get("framework") or "").strip()
        component_name = str(args.get("name") or "").strip()
        raw_target_path = str(args.get("target_path") or args.get("path") or "").strip()
        overwrite = bool(args.get("overwrite", False))
        props_schema = args.get("props_schema")
        auto_wire = bool(args.get("auto_wire", False))

        if not framework:
            raise ValueError("framework is required")
        if not component_name:
            raise ValueError("name is required")
        if not raw_target_path:
            raise ValueError("target_path is required")
        if props_schema is not None and not isinstance(props_schema, dict):
            raise ValueError("props_schema must be an object when provided")

        target = _resolve_workspace_path(raw_target_path)
        target.mkdir(parents=True, exist_ok=True)

        files, notes = _build_component_scaffold(framework, component_name, props_schema)
        transaction = _write_scaffold_files(target, files, overwrite)
        auto_wire_note = (
            "Auto-wiring is deferred in this release; generated files are intentionally isolated."
            if auto_wire
            else "Auto-wiring disabled by default; generated files remain isolated."
        )

        return {
            "ok": True,
            "framework": framework,
            "name": component_name,
            "target_path": str(target).replace("\\", "/"),
            "created_paths": transaction["created_paths"],
            "updated_paths": transaction["updated_paths"],
            "auto_wire_requested": auto_wire,
            "auto_wire_applied": False,
            "notes": notes + [auto_wire_note],
        }

    tools.register_tool(
        ToolDefinition(
            name="generate_component",
            description="Generate a starter UI component for vite-react/react or a snippet for static-site projects.",
            handler=generate_component_handler,
            parameters={
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "description": "vite-react | react | static-site"},
                    "name": {"type": "string", "description": "Component name to generate"},
                    "target_path": {"type": "string", "description": "Project root directory containing the app"},
                    "props_schema": {"type": "object", "description": "Optional prop-name map used to shape the starter component"},
                    "auto_wire": {"type": "boolean", "description": "Request automatic wiring into app entrypoints (deferred; currently not applied)"},
                    "overwrite": {"type": "boolean", "description": "Whether existing component files may be replaced; defaults to false"},
                },
                "required": ["framework", "name", "target_path"],
            },
        )
    )

    async def generate_route_handler(args: dict[str, Any]) -> dict[str, Any]:
        framework = str(args.get("framework") or "").strip()
        route_path = str(args.get("route_path") or "").strip()
        raw_target_path = str(args.get("target_path") or args.get("path") or "").strip()
        with_loader = bool(args.get("with_loader", False))
        with_tests = bool(args.get("with_tests", False))
        auto_wire = bool(args.get("auto_wire", False))
        overwrite = bool(args.get("overwrite", False))

        if not framework:
            raise ValueError("framework is required")
        if not route_path:
            raise ValueError("route_path is required")
        if not raw_target_path:
            raise ValueError("target_path is required")

        target = _resolve_workspace_path(raw_target_path)
        target.mkdir(parents=True, exist_ok=True)

        files, notes = _build_route_scaffold(framework, route_path, with_loader, with_tests)
        transaction = _write_scaffold_files(target, files, overwrite)
        auto_wire_note = (
            "Auto-wiring is deferred in this release; generated routes are intentionally isolated."
            if auto_wire
            else "Auto-wiring disabled by default; generated routes remain isolated."
        )

        return {
            "ok": True,
            "framework": framework,
            "route_path": route_path,
            "target_path": str(target).replace("\\", "/"),
            "created_paths": transaction["created_paths"],
            "updated_paths": transaction["updated_paths"],
            "auto_wire_requested": auto_wire,
            "auto_wire_applied": False,
            "notes": notes + [auto_wire_note],
        }

    tools.register_tool(
        ToolDefinition(
            name="generate_route",
            description="Generate a starter route for vite-react/react, fastapi, or static-site projects.",
            handler=generate_route_handler,
            parameters={
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "description": "vite-react | react | fastapi | static-site"},
                    "route_path": {"type": "string", "description": "Route path to generate, like /dashboard"},
                    "target_path": {"type": "string", "description": "Project root directory containing the app"},
                    "with_loader": {"type": "boolean", "description": "Whether to emit a basic loader function for React routes"},
                    "with_tests": {"type": "boolean", "description": "Whether to generate a basic test file for the route"},
                    "auto_wire": {"type": "boolean", "description": "Request automatic wiring into app routing entrypoints (deferred; currently not applied)"},
                    "overwrite": {"type": "boolean", "description": "Whether existing route files may be replaced; defaults to false"},
                },
                "required": ["framework", "route_path", "target_path"],
            },
        )
    )

    async def generate_report_handler(args: dict[str, Any]) -> dict[str, Any]:
        title = str(args.get("title") or "Generated Report").strip() or "Generated Report"
        output_format = str(args.get("format") or "markdown").strip().lower()
        raw_target_path = str(args.get("target_path") or "outputs/reports").strip()
        overwrite = bool(args.get("overwrite", False))
        summary = str(args.get("summary") or "").strip()
        sections = args.get("sections") or []
        if not isinstance(sections, list):
            raise ValueError("sections must be an array when provided")
        if output_format not in {"markdown", "html"}:
            raise ValueError("format must be one of: markdown, html")

        normalized_sections: list[dict[str, str]] = []
        for index, item in enumerate(sections, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"sections[{index - 1}] must be an object with heading/body fields")
            heading = str(item.get("heading") or f"Section {index}").strip() or f"Section {index}"
            body = str(item.get("body") or "").strip()
            normalized_sections.append({"heading": heading, "body": body})

        request_payload = {
            "title": title,
            "format": output_format,
            "summary": summary,
            "sections": normalized_sections,
            "template": args.get("template"),
            "data": args.get("data"),
        }
        request_hash = hashlib.sha256(
            json.dumps(request_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:12]

        safe_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "report"
        extension = "md" if output_format == "markdown" else "html"
        filename = f"{safe_title}-{request_hash}.{extension}"
        target_dir = _resolve_workspace_path(raw_target_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = (target_dir / filename).resolve()
        existed_before = target.exists()
        if existed_before and not overwrite:
            raise ValueError(f"target report already exists and overwrite=false: {target}")

        generated_at = datetime.now(timezone.utc).isoformat()
        if output_format == "markdown":
            markdown_lines = [f"# {title}", ""]
            if summary:
                markdown_lines.extend([summary, ""])
            markdown_lines.append(f"_Generated at {generated_at}_")
            for section in normalized_sections:
                markdown_lines.extend(["", f"## {section['heading']}", "", section["body"]])
            content = "\n".join(markdown_lines).strip() + "\n"
            mime_type = "text/markdown"
            kind = "document.markdown"
        else:
            section_html = "".join(
                [
                    (
                        "<section class=\"report-section\">"
                        f"<h2>{escape(section['heading'])}</h2>"
                        f"<p>{escape(section['body'])}</p>"
                        "</section>"
                    )
                    for section in normalized_sections
                ]
            )
            summary_html = f"<p class=\"summary\">{escape(summary)}</p>" if summary else ""
            content = (
                "<!doctype html>\n"
                "<html lang=\"en\">\n"
                "  <head>\n"
                "    <meta charset=\"UTF-8\" />\n"
                "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
                f"    <title>{escape(title)}</title>\n"
                "    <style>\n"
                "      :root { font-family: 'Times New Roman', Georgia, serif; color: #1b1e23; }\n"
                "      body { margin: 2.2rem auto; max-width: 760px; line-height: 1.55; padding: 0 1.2rem; }\n"
                "      h1 { margin-bottom: 0.5rem; }\n"
                "      .summary { font-size: 1.05rem; color: #2f3c4d; }\n"
                "      .meta { color: #6a7280; font-size: 0.9rem; }\n"
                "      .report-section { margin-top: 1.4rem; }\n"
                "      .report-section h2 { margin-bottom: 0.5rem; }\n"
                "      .report-section p { white-space: pre-wrap; }\n"
                "    </style>\n"
                "  </head>\n"
                "  <body>\n"
                f"    <h1>{escape(title)}</h1>\n"
                f"    {summary_html}\n"
                f"    <p class=\"meta\">Generated at {escape(generated_at)}</p>\n"
                f"    {section_html}\n"
                "  </body>\n"
                "</html>\n"
            )
            mime_type = "text/html"
            kind = "document.html"

        target.write_text(content, encoding="utf-8")
        normalized_path = str(target).replace("\\", "/")
        artifact = {
            "artifact_id": request_hash,
            "kind": kind,
            "path": normalized_path,
            "mime_type": mime_type,
            "title": title,
            "summary": summary or f"Generated {output_format} report",
            "generator": "generate_report",
            "backend": "document_backend",
            "provenance": {
                "request_hash": request_hash,
                "generated_at": generated_at,
                "output_format": output_format,
                "section_count": len(normalized_sections),
            },
            "preview": {
                "safe_inline": True,
            },
        }
        return {
            "ok": True,
            "title": title,
            "format": output_format,
            "path": normalized_path,
            "created_paths": [] if existed_before else [normalized_path],
            "updated_paths": [normalized_path] if existed_before else [],
            "artifacts": [artifact],
        }

    tools.register_tool(
        ToolDefinition(
            name="generate_report",
            description="Generate a deterministic markdown or HTML report from structured input and emit artifact metadata.",
            handler=generate_report_handler,
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Report title"},
                    "summary": {"type": "string", "description": "Optional report summary paragraph"},
                    "format": {"type": "string", "description": "markdown | html"},
                    "target_path": {"type": "string", "description": "Output directory path"},
                    "template": {"type": "string", "description": "Optional template identifier for reproducibility metadata"},
                    "data": {"type": "object", "description": "Optional structured source data for reproducibility metadata"},
                    "sections": {
                        "type": "array",
                        "description": "Ordered report sections",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "body": {"type": "string"},
                            },
                        },
                    },
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite an existing target file"},
                },
                "required": ["title", "format", "sections"],
            },
        )
    )

    # ── Chart helpers ────────────────────────────────────────────────────────

    def _svg_bar_chart(title: str, data: list[dict], width: int, height: int, color: str) -> str:
        ml, mr, mt, mb = 55, 20, 48, 58
        pw = width - ml - mr
        ph = height - mt - mb
        n = len(data)
        if n == 0:
            return f'<?xml version="1.0" encoding="UTF-8"?><svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"><rect width="{width}" height="{height}" fill="#f8fafc" rx="8"/><text x="{width//2}" y="{height//2}" text-anchor="middle" font-family="system-ui" fill="#94a3b8">No data</text></svg>'
        max_val = max(float(d.get("value", 0)) for d in data)
        if max_val <= 0:
            max_val = 1.0
        bar_slot = pw / n
        bar_w = bar_slot * 0.65
        bar_off = bar_slot * 0.175
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
            f'<rect width="{width}" height="{height}" fill="#f8fafc" rx="8"/>',
            f'<text x="{width/2:.1f}" y="30" text-anchor="middle" font-family="system-ui,sans-serif" font-size="14" font-weight="600" fill="#1e293b">{escape(title)}</text>',
        ]
        for gi in range(5):
            gy = mt + ph * gi / 4
            gv = max_val * (1 - gi / 4)
            lines.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + pw}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
            lines.append(f'<text x="{ml - 5}" y="{gy + 4:.1f}" text-anchor="end" font-family="system-ui,sans-serif" font-size="10" fill="#94a3b8">{gv:.0f}</text>')
        for i, d in enumerate(data):
            val = float(d.get("value", 0))
            bh = max(1.0, ph * val / max_val)
            bx = ml + i * bar_slot + bar_off
            by = mt + ph - bh
            lines.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" fill="{color}" rx="3" opacity="0.88"/>')
            vlbl = f"{val:.0f}"
            lines.append(f'<text x="{bx + bar_w / 2:.1f}" y="{by - 4:.1f}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" fill="{color}" font-weight="600">{escape(vlbl)}</text>')
            xlbl = escape(str(d.get("label", i + 1)))
            lines.append(f'<text x="{bx + bar_w / 2:.1f}" y="{mt + ph + 16:.1f}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" fill="#475569">{xlbl}</text>')
        lines.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + ph}" stroke="#cbd5e1" stroke-width="1.5"/>')
        lines.append(f'<line x1="{ml}" y1="{mt + ph}" x2="{ml + pw}" y2="{mt + ph}" stroke="#cbd5e1" stroke-width="1.5"/>')
        lines.append('</svg>')
        return '\n'.join(lines)

    def _svg_line_chart(title: str, data: list[dict], width: int, height: int, color: str) -> str:
        ml, mr, mt, mb = 55, 20, 48, 58
        pw = width - ml - mr
        ph = height - mt - mb
        n = len(data)
        if n == 0:
            return f'<?xml version="1.0" encoding="UTF-8"?><svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"><rect width="{width}" height="{height}" fill="#f8fafc" rx="8"/><text x="{width//2}" y="{height//2}" text-anchor="middle" font-family="system-ui" fill="#94a3b8">No data</text></svg>'
        max_val = max(float(d.get("value", 0)) for d in data)
        if max_val <= 0:
            max_val = 1.0
        pts = []
        for i, d in enumerate(data):
            val = float(d.get("value", 0))
            x = ml + (i / max(n - 1, 1)) * pw
            y = mt + ph - (val / max_val) * ph
            pts.append((x, y, d))
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
            f'<rect width="{width}" height="{height}" fill="#f8fafc" rx="8"/>',
            f'<text x="{width/2:.1f}" y="30" text-anchor="middle" font-family="system-ui,sans-serif" font-size="14" font-weight="600" fill="#1e293b">{escape(title)}</text>',
        ]
        for gi in range(5):
            gy = mt + ph * gi / 4
            gv = max_val * (1 - gi / 4)
            lines.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + pw}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
            lines.append(f'<text x="{ml - 5}" y="{gy + 4:.1f}" text-anchor="end" font-family="system-ui,sans-serif" font-size="10" fill="#94a3b8">{gv:.0f}</text>')
        area_pts = f"{ml:.1f},{mt + ph:.1f} " + " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts) + f" {ml + pw:.1f},{mt + ph:.1f}"
        lines.append(f'<polygon points="{area_pts}" fill="{color}" opacity="0.10"/>')
        poly_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)
        lines.append(f'<polyline points="{poly_pts}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y, d in pts:
            lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" stroke="#f8fafc" stroke-width="2"/>')
            xlbl = escape(str(d.get("label", "")))
            lines.append(f'<text x="{x:.1f}" y="{mt + ph + 16:.1f}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" fill="#475569">{xlbl}</text>')
        lines.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + ph}" stroke="#cbd5e1" stroke-width="1.5"/>')
        lines.append(f'<line x1="{ml}" y1="{mt + ph}" x2="{ml + pw}" y2="{mt + ph}" stroke="#cbd5e1" stroke-width="1.5"/>')
        lines.append('</svg>')
        return '\n'.join(lines)

    def _svg_pie_chart(title: str, data: list[dict], width: int, height: int) -> str:
        palette = ["#4f9cf4", "#f4a24f", "#4ff4a2", "#f44f9c", "#a24ff4", "#64d4a0", "#f46f4f", "#4fa2f4", "#c4f44f", "#f44fa2"]
        legend_w = 150
        chart_w = width - legend_w
        cx = chart_w // 2
        mt = 50
        cy = (height - mt) // 2 + mt
        r = min(cx - 20, (height - mt) // 2 - 20)
        total = sum(float(d.get("value", 0)) for d in data)
        if total <= 0:
            total = 1.0
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
            f'<rect width="{width}" height="{height}" fill="#f8fafc" rx="8"/>',
            f'<text x="{width/2:.1f}" y="30" text-anchor="middle" font-family="system-ui,sans-serif" font-size="14" font-weight="600" fill="#1e293b">{escape(title)}</text>',
        ]
        angle = -math.pi / 2
        for i, d in enumerate(data):
            val = float(d.get("value", 0))
            sweep = (val / total) * 2 * math.pi
            if sweep < 0.001:
                continue
            x1 = cx + r * math.cos(angle)
            y1 = cy + r * math.sin(angle)
            x2 = cx + r * math.cos(angle + sweep)
            y2 = cy + r * math.sin(angle + sweep)
            large = 1 if sweep > math.pi else 0
            clr = palette[i % len(palette)]
            lines.append(f'<path d="M {cx:.1f} {cy:.1f} L {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f} Z" fill="{clr}" stroke="#f8fafc" stroke-width="2"/>')
            angle += sweep
        lx = width - legend_w + 12
        for i, d in enumerate(data):
            clr = palette[i % len(palette)]
            ly = mt + i * 22
            if ly > height - 20:
                break
            val = float(d.get("value", 0))
            pct = val / total * 100
            lbl = escape(str(d.get("label", i + 1)))
            lines.append(f'<rect x="{lx}" y="{ly}" width="12" height="12" fill="{clr}" rx="2"/>')
            lines.append(f'<text x="{lx + 17}" y="{ly + 10}" font-family="system-ui,sans-serif" font-size="11" fill="#334155">{lbl} ({pct:.0f}%)</text>')
        lines.append('</svg>')
        return '\n'.join(lines)

    async def generate_chart_handler(args: dict[str, Any]) -> dict[str, Any]:
        title = str(args.get("title") or "Chart").strip() or "Chart"
        chart_type = str(args.get("chart_type") or "bar").strip().lower()
        raw_data = args.get("data") or []
        output_format = str(args.get("format") or "svg").strip().lower()
        raw_target_path = str(args.get("target_path") or "outputs/charts").strip()
        overwrite = bool(args.get("overwrite", False))
        width = max(200, int(args.get("width") or 620))
        height = max(120, int(args.get("height") or 380))
        color = str(args.get("color") or "#4f9cf4").strip() or "#4f9cf4"

        if chart_type not in {"bar", "line", "pie"}:
            raise ValueError("chart_type must be one of: bar, line, pie")
        if output_format not in {"svg", "html"}:
            raise ValueError("format must be one of: svg, html")
        if not isinstance(raw_data, list):
            raise ValueError("data must be an array of {label, value} objects")

        data_rows: list[dict] = []
        for item in raw_data:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            try:
                value = float(item.get("value", 0))
            except (TypeError, ValueError):
                value = 0.0
            data_rows.append({"label": label, "value": value})

        if chart_type == "bar":
            svg_content = _svg_bar_chart(title, data_rows, width, height, color)
        elif chart_type == "line":
            svg_content = _svg_line_chart(title, data_rows, width, height, color)
        else:
            svg_content = _svg_pie_chart(title, data_rows, width, height)

        import hashlib as _hlib
        request_payload = {"title": title, "chart_type": chart_type, "data": data_rows, "width": width, "height": height, "color": color}
        request_hash = _hlib.sha256(json.dumps(request_payload, sort_keys=True, default=str).encode()).hexdigest()[:12]
        safe_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "chart"

        if output_format == "svg":
            final_content = svg_content
            mime_type = "image/svg+xml"
            kind = f"chart.{chart_type}.svg"
            ext = "svg"
        else:
            final_content = (
                "<!doctype html>\n<html lang=\"en\">\n  <head>\n"
                "    <meta charset=\"UTF-8\" />\n"
                f"    <title>{escape(title)}</title>\n"
                "    <style>body{margin:0;background:#f8fafc;display:flex;align-items:center;justify-content:center;min-height:100vh}</style>\n"
                "  </head>\n  <body>\n"
                f"    {svg_content}\n"
                "  </body>\n</html>\n"
            )
            mime_type = "text/html"
            kind = f"chart.{chart_type}.html"
            ext = "html"

        filename = f"{safe_title}-{request_hash}.{ext}"
        target_dir = _resolve_workspace_path(raw_target_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = (target_dir / filename).resolve()
        existed_before = target.exists()
        if existed_before and not overwrite:
            raise ValueError(f"target chart already exists and overwrite=false: {target}")

        target.write_text(final_content, encoding="utf-8")
        normalized_path = str(target).replace("\\", "/")
        generated_at = datetime.now(timezone.utc).isoformat()
        artifact = {
            "artifact_id": request_hash,
            "kind": kind,
            "path": normalized_path,
            "mime_type": mime_type,
            "title": title,
            "summary": f"{chart_type.capitalize()} chart with {len(data_rows)} data points",
            "generator": "generate_chart",
            "backend": "chart_backend",
            "provenance": {
                "request_hash": request_hash,
                "generated_at": generated_at,
                "chart_type": chart_type,
                "data_points": len(data_rows),
                "output_format": output_format,
            },
            "preview": {"safe_inline": True},
        }
        return {
            "ok": True,
            "title": title,
            "chart_type": chart_type,
            "format": output_format,
            "path": normalized_path,
            "data_points": len(data_rows),
            "created_paths": [] if existed_before else [normalized_path],
            "updated_paths": [normalized_path] if existed_before else [],
            "artifacts": [artifact],
        }

    tools.register_tool(
        ToolDefinition(
            name="generate_chart",
            description="Generate a deterministic SVG or HTML chart (bar, line, pie) from structured tabular data and emit artifact metadata.",
            handler=generate_chart_handler,
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Chart title"},
                    "chart_type": {"type": "string", "description": "bar | line | pie"},
                    "data": {
                        "type": "array",
                        "description": "Array of {label, value} data points",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "number"},
                            },
                        },
                    },
                    "format": {"type": "string", "description": "svg | html"},
                    "target_path": {"type": "string", "description": "Output directory path"},
                    "width": {"type": "integer", "description": "SVG width in pixels (default 620)"},
                    "height": {"type": "integer", "description": "SVG height in pixels (default 380)"},
                    "color": {"type": "string", "description": "Primary color hex for bar/line charts (default #4f9cf4)"},
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite an existing target file"},
                },
                "required": ["title", "chart_type", "data", "format"],
            },
        )
    )

    # ── SVG asset helpers ─────────────────────────────────────────────────────

    def _svg_badge(label: str, value: str, label_color: str, value_color: str, height: int) -> str:
        label_w = max(30, len(label) * 7 + 16)
        value_w = max(30, len(value) * 7 + 16)
        total_w = label_w + value_w
        lx = label_w / 2
        vx = label_w + value_w / 2
        hy = height / 2 + 1
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg width="{total_w}" height="{height}" viewBox="0 0 {total_w} {height}" xmlns="http://www.w3.org/2000/svg" role="img">\n'
            '  <linearGradient id="gs" x2="0" y2="100%">'
            '<stop offset="0" stop-color="#fff" stop-opacity=".15"/>'
            '<stop offset="1" stop-opacity=".15"/>'
            '</linearGradient>\n'
            f'  <clipPath id="cr"><rect width="{total_w}" height="{height}" rx="4" fill="#fff"/></clipPath>\n'
            '  <g clip-path="url(#cr)">\n'
            f'    <rect width="{label_w}" height="{height}" fill="{label_color}"/>\n'
            f'    <rect x="{label_w}" width="{value_w}" height="{height}" fill="{value_color}"/>\n'
            f'    <rect width="{total_w}" height="{height}" fill="url(#gs)"/>\n'
            '  </g>\n'
            f'  <text x="{lx:.1f}" y="{hy + 1:.1f}" text-anchor="middle" font-family="DejaVu Sans,Verdana,sans-serif" font-size="11" fill="#010101" fill-opacity=".25">{escape(label)}</text>\n'
            f'  <text x="{lx:.1f}" y="{hy:.1f}" text-anchor="middle" font-family="DejaVu Sans,Verdana,sans-serif" font-size="11" fill="#fff">{escape(label)}</text>\n'
            f'  <text x="{vx:.1f}" y="{hy + 1:.1f}" text-anchor="middle" font-family="DejaVu Sans,Verdana,sans-serif" font-size="11" fill="#010101" fill-opacity=".25">{escape(value)}</text>\n'
            f'  <text x="{vx:.1f}" y="{hy:.1f}" text-anchor="middle" font-family="DejaVu Sans,Verdana,sans-serif" font-size="11" fill="#fff">{escape(value)}</text>\n'
            '</svg>'
        )

    _ICON_PATHS: dict[str, str] = {
        "check": '<circle cx="24" cy="24" r="22" fill="{color}"/><polyline points="12,24 21,33 36,14" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
        "circle": '<circle cx="24" cy="24" r="22" fill="{color}"/>',
        "info": '<circle cx="24" cy="24" r="22" fill="{color}"/><rect x="22" y="20" width="4" height="14" rx="2" fill="#fff"/><circle cx="24" cy="14" r="3" fill="#fff"/>',
        "warning": '<polygon points="24,4 44,42 4,42" fill="{color}" stroke="{color}" stroke-linejoin="round"/><rect x="22" y="18" width="4" height="12" rx="2" fill="#fff"/><circle cx="24" cy="36" r="3" fill="#fff"/>',
        "star": '<polygon points="24,4 29,19 45,19 32,28 37,44 24,35 11,44 16,28 3,19 19,19" fill="{color}"/>',
        "cross": '<circle cx="24" cy="24" r="22" fill="{color}"/><line x1="14" y1="14" x2="34" y2="34" stroke="#fff" stroke-width="4" stroke-linecap="round"/><line x1="34" y1="14" x2="14" y2="34" stroke="#fff" stroke-width="4" stroke-linecap="round"/>',
        "bolt": '<polygon points="28,4 14,26 24,26 20,44 34,22 24,22" fill="{color}"/>',
        "user": '<circle cx="24" cy="16" r="9" fill="{color}"/><path d="M4,44 C4,30 44,30 44,44" fill="{color}"/>',
        "gear": '<circle cx="24" cy="24" r="8" fill="#fff" stroke="{color}" stroke-width="3"/><circle cx="24" cy="24" r="22" fill="none" stroke="{color}" stroke-width="7" stroke-dasharray="8 6"/>',
        "arrow": '<polygon points="12,20 28,20 28,12 40,24 28,36 28,28 12,28" fill="{color}"/>',
    }

    def _svg_icon(icon_type: str, color: str, size: int) -> str:
        path_tpl = _ICON_PATHS.get(icon_type, _ICON_PATHS["circle"])
        path_svg = path_tpl.replace("{color}", color)
        scale = size / 48
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg width="{size}" height="{size}" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" role="img">\n'
            f'  <g transform="scale({scale:.4f})">{path_svg}</g>\n'
            '</svg>'
        )

    def _svg_diagram(steps: list[dict], direction: str, title: str) -> str:
        is_horiz = direction.lower() in {"horizontal", "h"}
        box_w, box_h = (140, 44) if is_horiz else (180, 44)
        gap = 48
        n = len(steps)
        if n == 0:
            return '<?xml version="1.0" encoding="UTF-8"?><svg width="200" height="80" xmlns="http://www.w3.org/2000/svg"><text x="100" y="44" text-anchor="middle" font-family="system-ui" fill="#94a3b8">No steps</text></svg>'
        arrow_size = 16
        if is_horiz:
            total_w = n * box_w + (n - 1) * gap + 40
            total_h = box_h + 80
        else:
            total_w = box_w + 60
            total_h = n * box_h + (n - 1) * gap + 80
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg width="{total_w}" height="{total_h}" viewBox="0 0 {total_w} {total_h}" xmlns="http://www.w3.org/2000/svg">',
            f'<rect width="{total_w}" height="{total_h}" fill="#f8fafc" rx="8"/>',
            f'<text x="{total_w/2:.1f}" y="28" text-anchor="middle" font-family="system-ui,sans-serif" font-size="14" font-weight="600" fill="#1e293b">{escape(title)}</text>',
        ]
        for i, step in enumerate(steps):
            label = escape(str(step.get("label") or f"Step {i + 1}"))
            if is_horiz:
                bx = 20 + i * (box_w + gap)
                by = 44
            else:
                bx = 30
                by = 44 + i * (box_h + gap)
            cx = bx + box_w / 2
            cy = by + box_h / 2
            lines.append(f'<rect x="{bx}" y="{by}" width="{box_w}" height="{box_h}" rx="6" fill="#4f9cf4" opacity="0.9"/>')
            lines.append(f'<text x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="12" font-weight="600" fill="#fff">{label}</text>')
            if i < n - 1:
                if is_horiz:
                    ax1 = bx + box_w
                    ay1 = by + box_h / 2
                    ax2 = ax1 + gap - arrow_size
                    lines.append(f'<line x1="{ax1}" y1="{ay1:.1f}" x2="{ax2}" y2="{ay1:.1f}" stroke="#94a3b8" stroke-width="2"/>')
                    lines.append(f'<polygon points="{ax2},{ay1 - 5:.1f} {ax2 + arrow_size},{ay1:.1f} {ax2},{ay1 + 5:.1f}" fill="#94a3b8"/>')
                else:
                    ax1 = bx + box_w / 2
                    ay1 = by + box_h
                    ay2 = ay1 + gap - arrow_size
                    lines.append(f'<line x1="{ax1:.1f}" y1="{ay1}" x2="{ax1:.1f}" y2="{ay2}" stroke="#94a3b8" stroke-width="2"/>')
                    lines.append(f'<polygon points="{ax1 - 5:.1f},{ay2} {ax1:.1f},{ay2 + arrow_size} {ax1 + 5:.1f},{ay2}" fill="#94a3b8"/>')
        lines.append('</svg>')
        return '\n'.join(lines)

    async def generate_svg_asset_handler(args: dict[str, Any]) -> dict[str, Any]:
        kind = str(args.get("kind") or "badge").strip().lower()
        title = str(args.get("title") or kind).strip() or kind
        raw_target_path = str(args.get("target_path") or "outputs/assets").strip()
        overwrite = bool(args.get("overwrite", False))

        if kind not in {"badge", "icon", "diagram", "custom"}:
            raise ValueError("kind must be one of: badge, icon, diagram, custom")

        generated_at = datetime.now(timezone.utc).isoformat()
        if kind == "badge":
            label = str(args.get("label") or "label").strip() or "label"
            value = str(args.get("value") or "value").strip() or "value"
            label_color = str(args.get("label_color") or "#555").strip() or "#555"
            value_color = str(args.get("value_color") or "#4f9cf4").strip() or "#4f9cf4"
            badge_height = max(16, int(args.get("height") or 20))
            svg_content = _svg_badge(label, value, label_color, value_color, badge_height)
            summary = f"Badge: {label} | {value}"
        elif kind == "icon":
            icon_type = str(args.get("icon_type") or "circle").strip().lower()
            if icon_type not in _ICON_PATHS:
                icon_type = "circle"
            color = str(args.get("color") or "#4f9cf4").strip() or "#4f9cf4"
            size = max(16, int(args.get("size") or 48))
            svg_content = _svg_icon(icon_type, color, size)
            summary = f"Icon: {icon_type} at {size}px"
        elif kind == "diagram":
            raw_steps = args.get("steps") or []
            if not isinstance(raw_steps, list):
                raise ValueError("steps must be an array when kind=diagram")
            steps = [{"label": str(s.get("label") or f"Step {i + 1}")} for i, s in enumerate(raw_steps) if isinstance(s, dict)]
            direction = str(args.get("direction") or "horizontal").strip().lower()
            svg_content = _svg_diagram(steps, direction, title)
            summary = f"Diagram with {len(steps)} steps"
        else:
            raw_markup = str(args.get("markup") or "").strip()
            if not raw_markup:
                raise ValueError("markup is required when kind=custom")
            svg_content = raw_markup
            summary = "Custom SVG asset"

        import hashlib as _hlib
        request_hash = _hlib.sha256((title + kind + svg_content[:200]).encode()).hexdigest()[:12]
        safe_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "asset"
        filename = f"{safe_title}-{request_hash}.svg"
        target_dir = _resolve_workspace_path(raw_target_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = (target_dir / filename).resolve()
        existed_before = target.exists()
        if existed_before and not overwrite:
            raise ValueError(f"target SVG asset already exists and overwrite=false: {target}")

        target.write_text(svg_content, encoding="utf-8")
        normalized_path = str(target).replace("\\", "/")
        artifact = {
            "artifact_id": request_hash,
            "kind": f"asset.svg.{kind}",
            "path": normalized_path,
            "mime_type": "image/svg+xml",
            "title": title,
            "summary": summary,
            "generator": "generate_svg_asset",
            "backend": "vector_backend",
            "provenance": {
                "request_hash": request_hash,
                "generated_at": generated_at,
                "kind": kind,
            },
            "preview": {"safe_inline": True},
        }
        return {
            "ok": True,
            "title": title,
            "kind": kind,
            "path": normalized_path,
            "created_paths": [] if existed_before else [normalized_path],
            "updated_paths": [normalized_path] if existed_before else [],
            "artifacts": [artifact],
        }

    tools.register_tool(
        ToolDefinition(
            name="generate_svg_asset",
            description="Generate a deterministic SVG asset (badge, icon, diagram, or custom markup) and emit artifact metadata.",
            handler=generate_svg_asset_handler,
            parameters={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "badge | icon | diagram | custom"},
                    "title": {"type": "string", "description": "Asset title for metadata"},
                    "target_path": {"type": "string", "description": "Output directory path"},
                    "label": {"type": "string", "description": "Left label text (badge only)"},
                    "value": {"type": "string", "description": "Right value text (badge only)"},
                    "label_color": {"type": "string", "description": "Left section background color (badge only, default #555)"},
                    "value_color": {"type": "string", "description": "Right section background color (badge only, default #4f9cf4)"},
                    "height": {"type": "integer", "description": "Badge height in px (badge only, default 20)"},
                    "icon_type": {"type": "string", "description": "check | circle | info | warning | star | cross | bolt | user | gear | arrow (icon only)"},
                    "color": {"type": "string", "description": "Icon fill color hex (icon only, default #4f9cf4)"},
                    "size": {"type": "integer", "description": "Icon size in px (icon only, default 48)"},
                    "steps": {
                        "type": "array",
                        "description": "Ordered step objects for diagram kind",
                        "items": {"type": "object", "properties": {"label": {"type": "string"}}},
                    },
                    "direction": {"type": "string", "description": "horizontal | vertical flow direction for diagrams"},
                    "markup": {"type": "string", "description": "Raw SVG markup (custom kind only)"},
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite an existing target file"},
                },
                "required": ["kind", "title"],
            },
        )
    )

    async def version_bump_handler(args: dict[str, Any]) -> dict[str, Any]:
        bump = str(args.get("bump", "patch")).strip().lower()
        set_version = str(args.get("set_version", "")).strip() or None
        dry_run = bool(args.get("dry_run", False))
        raw_files = args.get("files")
        target_files = [
            "pyproject.toml",
            "harness/__init__.py",
            "harness/api/server.py",
        ]
        if isinstance(raw_files, list) and raw_files:
            target_files = [str(v) for v in raw_files]

        pyproject = _resolve_workspace_path("pyproject.toml")
        if not pyproject.exists():
            raise ValueError("pyproject.toml not found; cannot determine current version")
        py_text = pyproject.read_text(encoding="utf-8", errors="replace")
        current_version = _parse_version_from_text(py_text)
        if not current_version:
            raise ValueError("Could not parse current semantic version from pyproject.toml")

        next_version = _bump_semver(current_version, bump, set_version)
        updated_files: list[str] = []
        planned_files: list[str] = []
        for raw_path in target_files:
            target = _resolve_workspace_path(raw_path)
            if not target.exists() or not target.is_file():
                continue
            content = target.read_text(encoding="utf-8", errors="replace")
            replaced = content.replace(current_version, next_version)
            if replaced != content:
                path_str = str(target).replace("\\", "/")
                planned_files.append(path_str)
                if not dry_run:
                    target.write_text(replaced, encoding="utf-8")
                    updated_files.append(path_str)

        return {
            "ok": True,
            "dry_run": dry_run,
            "current_version": current_version,
            "next_version": next_version,
            "updated_files": updated_files,
            "planned_files": planned_files,
        }

    tools.register_tool(
        ToolDefinition(
            name="version_bump",
            description="Bump semantic version across version-bearing files using patch/minor/major or explicit set mode.",
            handler=version_bump_handler,
            parameters={
                "type": "object",
                "properties": {
                    "bump": {"type": "string", "description": "patch | minor | major | set"},
                    "set_version": {"type": "string", "description": "Explicit semantic version when bump=set"},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Optional list of files to update"},
                    "dry_run": {"type": "boolean", "description": "Preview changes without writing files"},
                },
            },
        )
    )

    async def generate_release_notes_handler(args: dict[str, Any]) -> dict[str, Any]:
        version = str(args.get("version", "")).strip()
        if not version:
            raise ValueError("version is required")
        output_path = str(args.get("output_path", f"release_notes/RELEASE_NOTES_{version}.md")).strip()
        max_commits = int(args.get("max_commits", 25))
        dry_run = bool(args.get("dry_run", False))

        git_log_lines: list[str] = []
        git_error = None
        try:
            result = await execution.run_command("git", "log", "--oneline", "-n", str(max_commits))
            if result.returncode == 0:
                git_log_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            else:
                git_error = result.stderr.strip() or "git log failed"
        except Exception as exc:
            git_error = str(exc)

        body_lines = [
            f"# Release Notes {version}",
            "",
            f"Generated at {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Highlights",
            "",
            "- Placeholder summary: update with user-facing highlights.",
            "",
        ]

        categories: dict[str, list[str]] = {
            "features": [],
            "fixes": [],
            "chore": [],
            "other": [],
        }
        for line in git_log_lines:
            categories[_release_category_for_commit(line)].append(line)

        body_lines.extend(["## Features", ""])
        if categories["features"]:
            body_lines.extend([f"- {line}" for line in categories["features"]])
        else:
            body_lines.append("- None")

        body_lines.extend(["", "## Fixes", ""])
        if categories["fixes"]:
            body_lines.extend([f"- {line}" for line in categories["fixes"]])
        else:
            body_lines.append("- None")

        body_lines.extend(["", "## Chore", ""])
        if categories["chore"]:
            body_lines.extend([f"- {line}" for line in categories["chore"]])
        else:
            body_lines.append("- None")

        body_lines.extend(["", "## Other Changes", ""])
        if categories["other"]:
            body_lines.extend([f"- {line}" for line in categories["other"]])
        else:
            body_lines.append("- None")

        if not git_log_lines:
            body_lines.extend(["", "_No git log entries available._"])
        if git_error:
            body_lines.extend(["", f"_Git log warning: {git_error}_"])

        target = _resolve_workspace_path(output_path)
        content = "\n".join(body_lines) + "\n"
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "dry_run": dry_run,
            "version": version,
            "path": str(target).replace("\\", "/"),
            "bytes_written": 0 if dry_run else len(content.encode("utf-8")),
            "content_preview": content,
            "included_commits": len(git_log_lines),
            "git_warning": git_error,
        }

    tools.register_tool(
        ToolDefinition(
            name="generate_release_notes",
            description="Generate a release notes markdown file for a target version with recent git commits.",
            handler=generate_release_notes_handler,
            parameters={
                "type": "object",
                "properties": {
                    "version": {"type": "string", "description": "Version label used in release notes filename/content"},
                    "output_path": {"type": "string", "description": "Optional output markdown path"},
                    "max_commits": {"type": "integer", "description": "Max number of recent commits to include"},
                    "dry_run": {"type": "boolean", "description": "Preview release notes without writing a file"},
                },
                "required": ["version"],
            },
        )
    )

    async def tag_and_publish_release_handler(args: dict[str, Any]) -> dict[str, Any]:
        version = str(args.get("version", "")).strip()
        if not version:
            raise ValueError("version is required")
        tag = str(args.get("tag", f"v{version}")).strip()
        push_main = bool(args.get("push_main", False))
        dry_run = bool(args.get("dry_run", False))

        if dry_run:
            planned_commands = [
                f"git tag {shlex.quote(tag)}",
                f"git push origin {shlex.quote(tag)}",
            ]
            if push_main:
                planned_commands.append("git push origin main")
            return {
                "ok": True,
                "dry_run": True,
                "tag": tag,
                "push_main": push_main,
                "planned_commands": planned_commands,
                "push_main_result": None,
            }

        tag_result = await execution.run_command("git", "tag", tag)
        if tag_result.returncode != 0:
            return {
                "ok": False,
                "dry_run": False,
                "tag": tag,
                "step": "tag",
                "stdout": tag_result.stdout,
                "stderr": tag_result.stderr,
                "returncode": tag_result.returncode,
            }

        push_tag_result = await execution.run_command("git", "push", "origin", tag)
        if push_tag_result.returncode != 0:
            return {
                "ok": False,
                "dry_run": False,
                "tag": tag,
                "step": "push_tag",
                "stdout": push_tag_result.stdout,
                "stderr": push_tag_result.stderr,
                "returncode": push_tag_result.returncode,
            }

        push_main_result: dict[str, Any] | None = None
        if push_main:
            push_main_raw = await execution.run_command("git", "push", "origin", "main")
            push_main_result = {
                "returncode": push_main_raw.returncode,
                "stdout": push_main_raw.stdout,
                "stderr": push_main_raw.stderr,
            }

        return {
            "ok": True,
            "dry_run": False,
            "tag": tag,
            "push_main": push_main,
            "push_main_result": push_main_result,
        }

    tools.register_tool(
        ToolDefinition(
            name="tag_and_publish_release",
            description="Create a git tag and push it to origin, with optional main branch push.",
            handler=tag_and_publish_release_handler,
            parameters={
                "type": "object",
                "properties": {
                    "version": {"type": "string", "description": "Release version used to derive default tag"},
                    "tag": {"type": "string", "description": "Optional explicit tag name"},
                    "push_main": {"type": "boolean", "description": "Whether to push origin/main after pushing the tag"},
                    "dry_run": {"type": "boolean", "description": "Preview git commands without creating/pushing a tag"},
                },
                "required": ["version"],
            },
        )
    )

    async def write_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("target_path is required")
        content = str(args.get("content", ""))
        overwrite = bool(args.get("overwrite", True))
        target = _resolve_workspace_path(raw_path)
        existed_before = target.exists()
        if target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")
        if target.exists() and not overwrite:
            raise ValueError(f"target_path already exists and overwrite=false: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "bytes_written": len(content.encode("utf-8")),
            "overwrote": existed_before,
        }

    tools.register_tool(
        ToolDefinition(
            name="write_file",
            description="Write or overwrite a UTF-8 text file inside the allowed workspace. Use this to create app files like HTML, CSS, JS, JSON, or config files.",
            handler=write_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "content": {"type": "string", "description": "Full file contents to write"},
                    "overwrite": {"type": "boolean", "description": "Whether existing files may be replaced; defaults to true"},
                },
                "required": ["target_path", "content"],
            },
        )
    )

    async def append_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("target_path is required")
        content = str(args.get("content", ""))
        ensure_newline = bool(args.get("ensure_newline", True))
        target = _resolve_workspace_path(raw_path)
        if target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        existed_before = target.exists()
        prefix = ""
        if existed_before and ensure_newline:
            try:
                existing = target.read_text(encoding="utf-8", errors="replace")
            except Exception:
                existing = ""
            if existing and not existing.endswith("\n") and content and not content.startswith("\n"):
                prefix = "\n"

        to_write = f"{prefix}{content}"
        with target.open("a", encoding="utf-8") as f:
            f.write(to_write)

        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "bytes_written": len(to_write.encode("utf-8")),
            "appended": True,
            "created": not existed_before,
        }

    tools.register_tool(
        ToolDefinition(
            name="append_file",
            description="Append UTF-8 text to an existing file or create it if missing. Prefer this when user asks to keep existing content and add a new line.",
            handler=append_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "content": {"type": "string", "description": "Text to append"},
                    "ensure_newline": {"type": "boolean", "description": "Insert a newline before appended content when needed; defaults to true"},
                },
                "required": ["target_path", "content"],
            },
        )
    )

    async def replace_in_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        old_text = str(args.get("old_text", ""))
        new_text = str(args.get("new_text", ""))
        if not raw_path:
            raise ValueError("target_path is required")
        if not old_text:
            raise ValueError("old_text is required")

        count = int(args.get("count", 1))
        target = _resolve_workspace_path(raw_path)
        if not target.exists() or not target.is_file():
            raise ValueError(f"file not found: {target}")

        content = target.read_text(encoding="utf-8", errors="replace")
        replaced = content.replace(old_text, new_text, count if count > 0 else -1)
        occurrences = content.count(old_text)
        applied = min(occurrences, count) if count > 0 else occurrences
        if applied == 0:
            raise ValueError("old_text not found in target file")
        target.write_text(replaced, encoding="utf-8")

        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "replacements": applied,
            "bytes_written": len(replaced.encode("utf-8")),
        }

    tools.register_tool(
        ToolDefinition(
            name="replace_in_file",
            description="Replace text in an existing UTF-8 file. Use for targeted edits without rewriting whole files.",
            handler=replace_in_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "old_text": {"type": "string", "description": "Existing text to replace"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                    "count": {"type": "integer", "description": "Maximum replacements; defaults to 1"},
                },
                "required": ["target_path", "old_text", "new_text"],
            },
        )
    )

    async def json_edit_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        updates = args.get("updates")
        if not raw_path:
            raise ValueError("target_path is required")
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty object")

        target = _resolve_workspace_path(raw_path)
        document: dict[str, Any] = {}
        if target.exists() and target.is_file():
            raw = target.read_text(encoding="utf-8", errors="replace").strip()
            if raw:
                loaded = json.loads(raw)
                if not isinstance(loaded, dict):
                    raise ValueError("target JSON must be an object")
                document = loaded
        elif target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")

        for raw_key, value in updates.items():
            key_path = str(raw_key).strip()
            if not key_path:
                continue
            parts = [p for p in key_path.split(".") if p]
            cursor: dict[str, Any] = document
            for part in parts[:-1]:
                nxt = cursor.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cursor[part] = nxt
                cursor = nxt
            cursor[parts[-1]] = value

        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(document, indent=2, sort_keys=True)
        target.write_text(serialized + "\n", encoding="utf-8")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "updated_keys": sorted(str(k) for k in updates.keys()),
            "bytes_written": len((serialized + "\n").encode("utf-8")),
        }

    tools.register_tool(
        ToolDefinition(
            name="json_edit",
            description="Upsert keys in a JSON object file using dot-path keys (for example: scripts.build).",
            handler=json_edit_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "JSON file path relative to workspace root or absolute allowed path"},
                    "updates": {
                        "type": "object",
                        "description": "Map of dot-path keys to values (e.g. {'scripts.build':'vite build'})",
                    },
                },
                "required": ["target_path", "updates"],
            },
        )
    )

    async def insert_at_line_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("target_path is required")
        line_number = int(args.get("line_number", 0))
        content = str(args.get("content", ""))
        if line_number < 0:
            raise ValueError("line_number must be >= 0")

        target = _resolve_workspace_path(raw_path)
        if target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")

        existing = ""
        if target.exists() and target.is_file():
            existing = target.read_text(encoding="utf-8", errors="replace")

        lines = existing.splitlines()
        if line_number > len(lines):
            line_number = len(lines)
        lines.insert(line_number, content)

        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = "\n".join(lines)
        if existing.endswith("\n") or not existing:
            serialized += "\n"
        target.write_text(serialized, encoding="utf-8")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "inserted_at": line_number,
            "line_count": len(lines),
            "bytes_written": len(serialized.encode("utf-8")),
        }

    tools.register_tool(
        ToolDefinition(
            name="insert_at_line",
            description="Insert one line of text at a specific 0-based line index in a UTF-8 file.",
            handler=insert_at_line_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "line_number": {"type": "integer", "description": "0-based line index to insert at"},
                    "content": {"type": "string", "description": "Line content to insert"},
                },
                "required": ["target_path", "line_number", "content"],
            },
        )
    )

    async def delete_range_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        if not raw_path:
            raise ValueError("target_path is required")
        start_line = int(args.get("start_line", 1))
        end_line = int(args.get("end_line", start_line))
        if start_line < 1 or end_line < start_line:
            raise ValueError("line range must be valid and 1-based")

        target = _resolve_workspace_path(raw_path)
        if not target.exists() or not target.is_file():
            raise ValueError(f"file not found: {target}")

        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        if start_line > len(lines):
            raise ValueError("start_line exceeds file length")

        s = start_line - 1
        e = min(end_line, len(lines))
        removed_count = e - s
        new_lines = lines[:s] + lines[e:]
        serialized = "\n".join(new_lines)
        if content.endswith("\n") and serialized:
            serialized += "\n"
        target.write_text(serialized, encoding="utf-8")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "removed_lines": removed_count,
            "line_count": len(new_lines),
            "bytes_written": len(serialized.encode("utf-8")),
        }

    tools.register_tool(
        ToolDefinition(
            name="delete_range",
            description="Delete a 1-based inclusive line range from a UTF-8 file.",
            handler=delete_range_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "start_line": {"type": "integer", "description": "1-based starting line"},
                    "end_line": {"type": "integer", "description": "1-based ending line (inclusive)"},
                },
                "required": ["target_path", "start_line", "end_line"],
            },
        )
    )

    async def yaml_edit_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        updates = args.get("updates")
        if not raw_path:
            raise ValueError("target_path is required")
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty object")

        target = _resolve_workspace_path(raw_path)
        document: dict[str, Any] = {}
        if target.exists() and target.is_file():
            raw = target.read_text(encoding="utf-8", errors="replace")
            if raw.strip():
                loaded = yaml.safe_load(raw)
                if loaded is None:
                    document = {}
                elif not isinstance(loaded, dict):
                    raise ValueError("target YAML must be a mapping/object")
                else:
                    document = loaded
        elif target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")

        for raw_key, value in updates.items():
            key_path = str(raw_key).strip()
            if not key_path:
                continue
            parts = [p for p in key_path.split(".") if p]
            cursor: dict[str, Any] = document
            for part in parts[:-1]:
                nxt = cursor.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cursor[part] = nxt
                cursor = nxt
            cursor[parts[-1]] = value

        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = yaml.safe_dump(document, sort_keys=True, allow_unicode=False)
        target.write_text(serialized, encoding="utf-8")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "updated_keys": sorted(str(k) for k in updates.keys()),
            "bytes_written": len(serialized.encode("utf-8")),
        }

    tools.register_tool(
        ToolDefinition(
            name="yaml_edit",
            description="Upsert keys in a YAML mapping file using dot-path keys.",
            handler=yaml_edit_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "YAML file path relative to workspace root or absolute allowed path"},
                    "updates": {"type": "object", "description": "Map of dot-path keys to values"},
                },
                "required": ["target_path", "updates"],
            },
        )
    )

    _READ_FILE_MAX_CHARS_HARD_LIMIT = 48_000
    _SUPPORTED_ENCODINGS = {"utf-8", "utf-8-sig", "latin-1", "ascii"}

    async def read_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or args.get("target_path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")
        target = _resolve_workspace_path(raw_path)
        if not target.exists() or not target.is_file():
            raise ValueError(f"file not found: {target}")

        # Encoding
        raw_enc = str(args.get("encoding") or "utf-8").strip().lower().replace("_", "-")
        if raw_enc not in _SUPPORTED_ENCODINGS:
            raise ValueError(f"encoding must be one of: {', '.join(sorted(_SUPPORTED_ENCODINGS))}")
        encoding_used = raw_enc

        # Read raw bytes for stats
        raw_bytes = target.read_bytes()
        total_bytes = len(raw_bytes)
        try:
            full_text = raw_bytes.decode(encoding_used, errors="replace")
        except LookupError:
            full_text = raw_bytes.decode("utf-8", errors="replace")
            encoding_used = "utf-8"

        all_lines = full_text.splitlines(keepends=True)
        total_lines = len(all_lines)

        # Line-range bounds
        raw_start = args.get("start_line")
        raw_end = args.get("end_line")
        start_line: int = max(1, int(raw_start)) if raw_start is not None else 1
        end_line: int = min(total_lines, int(raw_end)) if raw_end is not None else total_lines

        if start_line > total_lines:
            start_line = total_lines
        if end_line < start_line:
            end_line = start_line

        selected = all_lines[start_line - 1 : end_line]
        windowed_text = "".join(selected)

        # Character cap
        max_chars = min(
            max(1, int(args.get("max_chars", _READ_FILE_MAX_CHARS_HARD_LIMIT))),
            _READ_FILE_MAX_CHARS_HARD_LIMIT,
        )
        truncated_chars = len(windowed_text) > max_chars
        content = windowed_text[:max_chars]

        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "content": content,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": total_lines,
            "total_bytes": total_bytes,
            "encoding_used": encoding_used,
            "truncated": truncated_chars,
        }

    tools.register_tool(
        ToolDefinition(
            name="read_file",
            description=(
                "Read a text file from the allowed workspace. "
                "Supports line-range selection (start_line/end_line), encoding selection, "
                "and a hard cap of 48 000 chars. Use this before edits to inspect existing content."
            ),
            handler=read_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "start_line": {"type": "integer", "description": "1-based start line (default 1)"},
                    "end_line": {"type": "integer", "description": "1-based end line inclusive (default: last line)"},
                    "max_chars": {"type": "integer", "description": "Character cap (default and max: 48000)"},
                    "encoding": {"type": "string", "description": "utf-8 | utf-8-sig | latin-1 | ascii (default utf-8)"},
                },
                "required": ["path"],
            },
        )
    )

    async def list_directory_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or args.get("directory_path") or ".").strip()
        target = _resolve_workspace_path(raw_path)
        if not target.exists() or not target.is_dir():
            raise ValueError(f"directory not found: {target}")
        max_entries = max(1, min(int(args.get("max_entries", 200)), 1000))
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        rows: list[dict[str, Any]] = []
        for item in entries[:max_entries]:
            rows.append(
                {
                    "name": item.name,
                    "path": str(item).replace("\\", "/"),
                    "is_dir": item.is_dir(),
                }
            )
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "entries": rows,
            "truncated": len(entries) > max_entries,
        }

    tools.register_tool(
        ToolDefinition(
            name="list_directory",
            description="List files and folders under a workspace directory.",
            handler=list_directory_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to workspace root (default .)"},
                    "max_entries": {"type": "integer", "description": "Maximum entries returned (default 200)"},
                },
            },
        )
    )

    async def rename_or_move_handler(args: dict[str, Any]) -> dict[str, Any]:
        source_raw = str(args.get("source_path") or "").strip()
        destination_raw = str(args.get("destination_path") or "").strip()
        if not source_raw or not destination_raw:
            raise ValueError("source_path and destination_path are required")
        source = _resolve_workspace_path(source_raw)
        destination = _resolve_workspace_path(destination_raw)
        if not source.exists():
            raise ValueError(f"source_path not found: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        return {
            "ok": True,
            "source_path": str(source).replace("\\", "/"),
            "destination_path": str(destination).replace("\\", "/"),
        }

    tools.register_tool(
        ToolDefinition(
            name="rename_or_move",
            description="Rename or move a file/directory inside the workspace.",
            handler=rename_or_move_handler,
            parameters={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                },
                "required": ["source_path", "destination_path"],
            },
        )
    )

    async def delete_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or args.get("target_path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")
        if str(args.get("confirm", "")).strip() != "I_UNDERSTAND_DELETE":
            raise PermissionError("delete_file requires confirm='I_UNDERSTAND_DELETE'")
        target = _resolve_workspace_path(raw_path)
        if not target.exists():
            return {"ok": True, "path": str(target).replace("\\", "/"), "deleted": False}
        if target.is_dir():
            for root, dirs, files in os.walk(target, topdown=False):
                for f in files:
                    Path(root, f).unlink(missing_ok=True)
                for d in dirs:
                    Path(root, d).rmdir()
            target.rmdir()
        else:
            target.unlink(missing_ok=True)
        return {"ok": True, "path": str(target).replace("\\", "/"), "deleted": True}

    tools.register_tool(
        ToolDefinition(
            name="delete_file",
            description="Delete a file or directory inside the workspace. Requires explicit confirmation token.",
            handler=delete_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "confirm": {"type": "string", "description": "Must be exactly I_UNDERSTAND_DELETE"},
                },
                "required": ["path", "confirm"],
            },
        )
    )

    async def search_workspace_handler(args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip().lower()
        if not query:
            raise ValueError("query is required")
        max_results = max(1, min(int(args.get("max_results", 50)), 500))
        rows: list[dict[str, Any]] = []
        for root, _, files in os.walk(execution.default_cwd):
            for file_name in files:
                full = Path(root) / file_name
                rel = str(full.relative_to(execution.default_cwd)).replace("\\", "/")
                matched = query in rel.lower()
                if not matched:
                    try:
                        text = full.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    idx = text.lower().find(query)
                    if idx >= 0:
                        snippet_start = max(0, idx - 80)
                        snippet_end = min(len(text), idx + 120)
                        rows.append({"path": rel, "snippet": text[snippet_start:snippet_end]})
                else:
                    rows.append({"path": rel, "snippet": ""})
                if len(rows) >= max_results:
                    return {"ok": True, "query": query, "results": rows, "truncated": True}
        return {"ok": True, "query": query, "results": rows, "truncated": False}

    tools.register_tool(
        ToolDefinition(
            name="search_workspace",
            description="Search workspace paths and file contents for a query string.",
            handler=search_workspace_handler,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "Maximum matches to return"},
                },
                "required": ["query"],
            },
        )
    )

    async def run_project_check_handler(args: dict[str, Any]) -> dict[str, Any]:
        check = str(args.get("check") or "").strip().lower()
        cwd = args.get("cwd")
        mapping: dict[str, tuple[str, list[str]]] = {
            "python_tests": ("python", ["-m", "pytest", "-q"]),
            "npm_test": ("npm", ["test"]),
            "npm_build": ("npm", ["run", "build"]),
            "python_check": ("python", ["-m", "pytest", "-q"]),
        }
        if check not in mapping:
            raise ValueError("check must be one of: python_tests, python_check, npm_test, npm_build")
        command, command_args = mapping[check]
        try:
            result = await execution.run_command(command, *command_args, cwd=cwd)
        except ExecutionDeniedError as exc:
            return {"ok": False, "error": str(exc), "check": check}
        return {
            "ok": result.returncode == 0,
            "check": check,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
        }

    tools.register_tool(
        ToolDefinition(
            name="run_project_check",
            description="Run approved project checks like pytest and npm build via a constrained wrapper.",
            handler=run_project_check_handler,
            parameters={
                "type": "object",
                "properties": {
                    "check": {"type": "string", "description": "python_tests | python_check | npm_test | npm_build"},
                    "cwd": {"type": "string", "description": "Optional working directory"},
                },
                "required": ["check"],
            },
        )
    )

    async def run_tests_handler(args: dict[str, Any]) -> dict[str, Any]:
        def _parse_pytest_failures(text: str) -> tuple[list[str], int | None]:
            lines = text.splitlines()
            failures = [line.strip() for line in lines if line.startswith("FAILED ")]
            failed_count: int | None = None
            match = re.search(r"(\d+)\s+failed", text)
            if match:
                failed_count = int(match.group(1))
            return failures[:20], failed_count

        def _parse_npm_failures(text: str) -> tuple[list[str], int | None]:
            lines = text.splitlines()
            failures: list[str] = []
            for raw in lines:
                line = raw.strip()
                if line.startswith("FAIL "):
                    failures.append(line)
                elif " failed" in line.lower() and ("tests" in line.lower() or "suites" in line.lower()):
                    failures.append(line)

            failed_count: int | None = None
            suites = re.search(r"Test Suites:\s*(\d+)\s*failed", text, flags=re.IGNORECASE)
            tests = re.search(r"Tests:\s*(\d+)\s*failed", text, flags=re.IGNORECASE)
            if tests:
                failed_count = int(tests.group(1))
            elif suites:
                failed_count = int(suites.group(1))
            return failures[:20], failed_count

        framework = str(args.get("framework", "auto")).strip().lower()
        target = str(args.get("target", "")).strip()
        cwd = args.get("cwd")

        if framework not in {"auto", "python", "npm"}:
            raise ValueError("framework must be one of: auto, python, npm")

        resolved_framework = framework
        if resolved_framework == "auto":
            root = execution.default_cwd if not cwd else _resolve_workspace_path(str(cwd))
            if (root / "package.json").exists():
                resolved_framework = "npm"
            else:
                resolved_framework = "python"

        if resolved_framework == "python":
            command = "python"
            cmd_args = ["-m", "pytest", "-q"]
            if target:
                cmd_args.append(target)
        else:
            command = "npm"
            cmd_args = ["test"]
            if target:
                cmd_args.extend(["--", target])

        try:
            result = await execution.run_command(command, *cmd_args, cwd=cwd)
        except ExecutionDeniedError as exc:
            return {"ok": False, "error": str(exc), "framework": resolved_framework}

        merged_output = f"{result.stdout}\n{result.stderr}".strip()
        if resolved_framework == "python":
            failure_summary, failed_count = _parse_pytest_failures(merged_output)
        else:
            failure_summary, failed_count = _parse_npm_failures(merged_output)

        return {
            "ok": result.returncode == 0,
            "framework": resolved_framework,
            "command": " ".join([command, *cmd_args]),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
            "failure_summary": failure_summary,
            "failed_count": failed_count,
        }

    tools.register_tool(
        ToolDefinition(
            name="run_tests",
            description="Run tests for python or npm projects, with optional target filter.",
            handler=run_tests_handler,
            parameters={
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "description": "auto | python | npm"},
                    "target": {"type": "string", "description": "Optional test target or pattern"},
                    "cwd": {"type": "string", "description": "Optional working directory"},
                },
            },
        )
    )

    async def lint_and_fix_handler(args: dict[str, Any]) -> dict[str, Any]:
        framework = str(args.get("framework", "auto")).strip().lower()
        fix = bool(args.get("fix", False))
        cwd = args.get("cwd")

        if framework not in {"auto", "python", "npm"}:
            raise ValueError("framework must be one of: auto, python, npm")

        resolved_framework = framework
        if resolved_framework == "auto":
            root = execution.default_cwd if not cwd else _resolve_workspace_path(str(cwd))
            if (root / "package.json").exists():
                resolved_framework = "npm"
            else:
                resolved_framework = "python"

        if resolved_framework == "python":
            command = "python"
            cmd_args = ["-m", "ruff", "check", "."]
            if fix:
                cmd_args.append("--fix")
        else:
            command = "npm"
            cmd_args = ["run", "lint"]
            if fix:
                cmd_args.extend(["--", "--fix"])

        try:
            result = await execution.run_command(command, *cmd_args, cwd=cwd)
        except ExecutionDeniedError as exc:
            return {"ok": False, "error": str(exc), "framework": resolved_framework}

        return {
            "ok": result.returncode == 0,
            "framework": resolved_framework,
            "fix": fix,
            "command": " ".join([command, *cmd_args]),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
        }

    tools.register_tool(
        ToolDefinition(
            name="lint_and_fix",
            description="Run lint checks (and optional auto-fix) for python or npm projects.",
            handler=lint_and_fix_handler,
            parameters={
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "description": "auto | python | npm"},
                    "fix": {"type": "boolean", "description": "Apply automatic fixes when supported"},
                    "cwd": {"type": "string", "description": "Optional working directory"},
                },
            },
        )
    )

    # ── patch_file ────────────────────────────────────────────────────────────

    def _apply_unified_patch(original_lines: list[str], patch_text: str) -> tuple[list[str], int, int, list[str]]:
        """Apply a unified-diff patch to a list of lines.

        Returns (result_lines, hunks_applied, hunks_rejected, rejection_details).
        Lines should NOT include trailing newlines for matching, but the result
        preserves whatever endings were already in original_lines.
        """
        import re as _re

        HUNK_HEADER = _re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

        class _Hunk:
            def __init__(self, src_start: int, src_count: int, lines: list[str]) -> None:
                self.src_start = src_start  # 1-based
                self.src_count = src_count
                self.lines = lines  # raw diff lines starting with ' ', '+', '-'

        # ── Parse patch into hunks ──────────────────────────────────────────
        hunks: list[_Hunk] = []
        current_hunk_lines: list[str] = []
        current_src_start = 0
        current_src_count = 0
        in_hunk = False
        for raw_line in patch_text.splitlines():
            m = HUNK_HEADER.match(raw_line)
            if m:
                if current_hunk_lines:
                    hunks.append(_Hunk(current_src_start, current_src_count, current_hunk_lines))
                    current_hunk_lines = []
                in_hunk = True
                current_src_start = int(m.group(1))
                current_src_count = int(m.group(2)) if m.group(2) is not None else 1
                continue
            if in_hunk and raw_line and raw_line[0] in (" ", "+", "-"):
                current_hunk_lines.append(raw_line)
        if current_hunk_lines:
            hunks.append(_Hunk(current_src_start, current_src_count, current_hunk_lines))

        if not hunks:
            return original_lines, 0, 1, ["patch contains no recognisable hunks"]

        # ── Strip line endings from originals for context matching ──────────
        stripped_originals = [ln.rstrip("\r\n") for ln in original_lines]

        result = list(original_lines)
        offset = 0
        hunks_applied = 0
        hunks_rejected = 0
        rejection_details: list[str] = []

        for hunk in hunks:
            ctx_before = [ln[1:] for ln in hunk.lines if ln[0] == " "]
            removals = [ln[1:] for ln in hunk.lines if ln[0] == "-"]
            # Expected source block = context + removals in order
            expected: list[str] = []
            for ln in hunk.lines:
                if ln[0] in (" ", "-"):
                    expected.append(ln[1:])

            # Locate expected block starting near hunk's declared src line
            # (adjusting by accumulated offset from prior hunks)
            anchor = hunk.src_start - 1 + offset  # 0-based
            search_start = max(0, anchor - 5)
            search_end = min(len(stripped_originals), anchor + max(10, len(expected) + 5))
            found_at = -1
            for i in range(search_start, search_end):
                candidate = stripped_originals[i : i + len(expected)]
                if candidate == expected:
                    found_at = i
                    break

            if found_at == -1:
                hunks_rejected += 1
                rejection_details.append(
                    f"hunk @@ -{hunk.src_start},{hunk.src_count} @@: context not found near line {anchor + 1}"
                )
                continue

            # Build replacement block
            replacement: list[str] = []
            for ln in hunk.lines:
                if ln[0] == " ":
                    # Preserve original ending
                    orig_idx = found_at + expected.index(ln[1:])
                    replacement.append(result[orig_idx])
                elif ln[0] == "+":
                    replacement.append(ln[1:] + "\n")
                # "-" lines are dropped

            result[found_at : found_at + len(expected)] = replacement
            stripped_originals[found_at : found_at + len(expected)] = [r.rstrip("\r\n") for r in replacement]
            offset += len(replacement) - len(expected)
            hunks_applied += 1

        return result, hunks_applied, hunks_rejected, rejection_details

    async def patch_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("target_path") or args.get("path") or "").strip()
        patch_text = str(args.get("patch") or "").strip()
        dry_run = bool(args.get("dry_run", False))
        allow_creation = bool(args.get("allow_creation", False))

        if not raw_path:
            raise ValueError("target_path is required")
        if not patch_text:
            raise ValueError("patch is required and must be a non-empty unified diff string")

        target = _resolve_workspace_path(raw_path)
        if target.exists() and target.is_dir():
            raise ValueError(f"target_path points to a directory: {target}")
        if not target.exists() and not allow_creation:
            raise ValueError(f"target file does not exist and allow_creation=false: {target}")

        if target.exists():
            original_text = target.read_text(encoding="utf-8", errors="replace")
        else:
            original_text = ""

        original_lines = original_text.splitlines(keepends=True)
        line_count_before = len(original_lines)

        result_lines, hunks_applied, hunks_rejected, rejection_details = _apply_unified_patch(original_lines, patch_text)
        line_count_after = len(result_lines)
        created = not target.exists()

        if hunks_rejected > 0 and hunks_applied == 0:
            raise ValueError(
                f"patch could not be applied: all {hunks_rejected} hunk(s) rejected. "
                + "; ".join(rejection_details)
            )

        result_text = "".join(result_lines)
        normalized_path = str(target).replace("\\", "/")

        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result_text, encoding="utf-8")

        summary = (
            f"applied {hunks_applied} hunk(s) to {normalized_path}"
            + (f" ({hunks_rejected} rejected)" if hunks_rejected else "")
        )

        return {
            "ok": True,
            "path": normalized_path,
            "dry_run": dry_run,
            "hunks_applied": hunks_applied,
            "hunks_rejected": hunks_rejected,
            "rejection_details": rejection_details,
            "line_count_before": line_count_before,
            "line_count_after": line_count_after,
            "bytes_written": len(result_text.encode("utf-8")) if not dry_run else 0,
            "created": created and not dry_run,
            "patch_summary": summary,
            "created_paths": [normalized_path] if created and not dry_run else [],
            "updated_paths": [normalized_path] if not created and not dry_run else [],
        }

    tools.register_tool(
        ToolDefinition(
            name="patch_file",
            description=(
                "Apply a unified diff patch to a file in the workspace. "
                "Locates each hunk by context lines, applies additions and removals, "
                "and reports applied vs rejected hunks. Supports dry_run to preview changes."
            ),
            handler=patch_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "target_path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "patch": {"type": "string", "description": "Unified diff string (output of git diff or diff -u)"},
                    "dry_run": {"type": "boolean", "description": "Preview the patched result without writing (default false)"},
                    "allow_creation": {"type": "boolean", "description": "Create the file if it does not yet exist (default false)"},
                },
                "required": ["target_path", "patch"],
            },
        )
    )

    # ── install_dependencies ──────────────────────────────────────────────────

    async def install_dependencies_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_pm = str(args.get("package_manager") or "auto").strip().lower()
        packages: list[str] = []
        raw_pkgs = args.get("packages")
        if isinstance(raw_pkgs, list):
            packages = [str(p).strip() for p in raw_pkgs if str(p).strip()]
        dev = bool(args.get("dev", False))
        raw_cwd = args.get("target_path") or args.get("cwd")
        cwd: str | None = str(raw_cwd).strip() if raw_cwd else None
        dry_run = bool(args.get("dry_run", False))

        if raw_pm not in {"auto", "pip", "npm"}:
            raise ValueError("package_manager must be one of: auto, pip, npm")

        resolved_pm = raw_pm
        if resolved_pm == "auto":
            search_root = _resolve_workspace_path(cwd) if cwd else execution.default_cwd
            resolved_pm = "npm" if (search_root / "package.json").exists() else "pip"

        # Build command
        if resolved_pm == "npm":
            if packages:
                cmd_args = ["install"] + packages
                if dev:
                    cmd_args.append("--save-dev")
            else:
                cmd_args = ["install"]
            command = "npm"
            lockfile = "package-lock.json"
        else:  # pip
            if packages:
                cmd_args = ["-m", "pip", "install"] + packages
            else:
                cmd_args = ["-m", "pip", "install", "-r", "requirements.txt"]
            command = "python"
            lockfile = "requirements.txt"

        full_command = " ".join([command] + cmd_args)

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "package_manager": resolved_pm,
                "command": full_command,
                "packages": packages,
                "dev": dev,
                "note": f"dry_run=true — no packages installed. Would run: {full_command}",
                "created_paths": [],
                "updated_paths": [],
            }

        try:
            result = await execution.run_command(command, *cmd_args, cwd=cwd)
        except ExecutionDeniedError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "package_manager": resolved_pm,
                "command": full_command,
                "packages": packages,
                "created_paths": [],
                "updated_paths": [],
            }

        # Detect lockfile/requirements changes
        updated_paths: list[str] = []
        if result.returncode == 0:
            search_root = _resolve_workspace_path(cwd) if cwd else execution.default_cwd
            lf = (search_root / lockfile).resolve()
            if lf.exists():
                updated_paths.append(str(lf).replace("\\", "/"))

        return {
            "ok": result.returncode == 0,
            "package_manager": resolved_pm,
            "command": full_command,
            "packages": packages,
            "dev": dev,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
            "created_paths": [],
            "updated_paths": updated_paths,
        }

    tools.register_tool(
        ToolDefinition(
            name="install_dependencies",
            description=(
                "Install packages using pip or npm. Auto-detects package manager from workspace layout. "
                "If packages list is omitted, runs a clean install from the existing lock/requirements file. "
                "Supports dry_run to preview the command without running it."
            ),
            handler=install_dependencies_handler,
            parameters={
                "type": "object",
                "properties": {
                    "package_manager": {"type": "string", "description": "auto | pip | npm (default auto)"},
                    "packages": {
                        "type": "array",
                        "description": "Package names to install. Omit to install from lockfile.",
                        "items": {"type": "string"},
                    },
                    "dev": {"type": "boolean", "description": "Install as dev dependency (npm --save-dev only)"},
                    "target_path": {"type": "string", "description": "Working directory to run install in (optional)"},
                    "dry_run": {"type": "boolean", "description": "Preview install command without executing (default false)"},
                },
            },
        )
    )

    # ── index_project ─────────────────────────────────────────────────────────

    _INDEX_IGNORE_DIRS: frozenset[str] = frozenset({
        ".git", "node_modules", ".venv", "venv", "__pycache__", ".harness",
        "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "titantshift_harness.egg-info", ".eggs",
    })

    def _classify_file_kind(rel_str: str, name: str, suffix: str) -> str:
        nl = "/" + rel_str.lower().replace("\\", "/")
        if re.search(r"(^/tests?/|/tests?/|/__tests__/|test_[^/]+\.py$|[^/]+\.(test|spec)\.[tj]sx?$)", nl):
            return "test"
        if name in {"package.json", "pyproject.toml", "requirements.txt", "pipfile", "setup.py", "setup.cfg"}:
            return "dependency_manifest"
        if re.search(r"/(routes?|pages?|views?)/", nl):
            return "route"
        if re.search(r"/components?/", nl):
            return "component"
        if re.search(r"/(services?|clients?|hooks?)/", nl):
            return "service"
        if suffix in {"tsx", "jsx"}:
            return "component"
        if suffix in {"json", "toml", "yaml", "yml", "ini", "cfg", "env"}:
            return "config"
        if suffix in {"md", "txt", "rst"}:
            return "doc"
        if suffix in {"css", "scss", "less"}:
            return "style"
        return "module"

    async def index_project_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_root = args.get("root_path") or "."
        max_files = max(1, int(args.get("max_files") or 500))
        workspace = _resolve_workspace_path(str(raw_root))
        index_file = workspace / ".harness" / "project_index.json"
        indexed: list[dict[str, Any]] = []
        skipped = 0

        for path in sorted(workspace.rglob("*")):
            if not path.is_file():
                continue
            parts_set = set(path.relative_to(workspace).parts)
            if parts_set & _INDEX_IGNORE_DIRS:
                continue
            if len(indexed) >= max_files:
                skipped += 1
                continue
            try:
                rel = str(path.relative_to(workspace)).replace("\\", "/")
                kind = _classify_file_kind(rel, path.name.lower(), path.suffix.lstrip(".").lower())
                indexed.append({"path": rel, "kind": kind, "size_bytes": path.stat().st_size})
            except Exception:
                skipped += 1

        kind_counts: dict[str, int] = {}
        for item in indexed:
            kind_counts[item["kind"]] = kind_counts.get(item["kind"], 0) + 1

        index_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "workspace": str(workspace),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_files": len(indexed),
            "by_kind": kind_counts,
            "files": indexed,
        }
        index_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "workspace": str(workspace),
            "total_files_indexed": len(indexed),
            "skipped": skipped,
            "by_kind": kind_counts,
            "index_file": str(index_file.relative_to(workspace)).replace("\\", "/"),
            "updated_paths": [str(index_file)],
        }

    tools.register_tool(
        ToolDefinition(
            name="index_project",
            description=(
                "Walk the workspace directory tree, classify every file by kind "
                "(component, route, service, module, test, config, style, doc, dependency_manifest), "
                "and write a project_index.json to .harness/. "
                "Run this before read_context or propose_wiring to enable file discovery."
            ),
            handler=index_project_handler,
            parameters={
                "type": "object",
                "properties": {
                    "root_path": {"type": "string", "description": "Workspace root to index (default '.')"},
                    "max_files": {"type": "integer", "description": "Max files to index (default 500)"},
                },
            },
        )
    )

    # ── read_context ──────────────────────────────────────────────────────────

    _READ_CONTEXT_TOKEN_LIMIT = 32_000
    _READ_CONTEXT_CHARS_PER_TOKEN = 4

    async def read_context_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_paths = args.get("paths") or []
        query = str(args.get("query") or "").strip()
        token_budget = min(int(args.get("token_budget") or 8_000), _READ_CONTEXT_TOKEN_LIMIT)
        root_raw = args.get("root_path") or "."
        workspace = _resolve_workspace_path(str(root_raw))
        char_budget = token_budget * _READ_CONTEXT_CHARS_PER_TOKEN

        # Resolve explicit paths first; if none given, try project index
        candidates: list[str] = []
        if isinstance(raw_paths, list) and raw_paths:
            candidates = [str(p).strip() for p in raw_paths if str(p).strip()]
        else:
            index_file = workspace / ".harness" / "project_index.json"
            if index_file.exists():
                try:
                    idx = json.loads(index_file.read_text(encoding="utf-8"))
                    all_files: list[dict[str, Any]] = idx.get("files", [])
                    if query:
                        words = [w for w in re.split(r"\W+", query.lower()) if w]

                        def _score(item: dict[str, Any]) -> int:
                            p = item.get("path", "").lower()
                            return sum(1 for w in words if w in p)

                        all_files = sorted(all_files, key=_score, reverse=True)
                    candidates = [
                        item["path"] for item in all_files
                        if item.get("kind") not in {"doc", "config"}
                    ][:50]
                except Exception:
                    pass

        files_out: list[dict[str, Any]] = []
        total_chars = 0
        truncated = False

        for rel_path in candidates:
            if total_chars >= char_budget:
                truncated = True
                break
            abs_path = (
                Path(rel_path).resolve()
                if Path(rel_path).is_absolute()
                else workspace / rel_path
            )
            if not abs_path.is_file():
                continue
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                remaining = char_budget - total_chars
                clipped = content[:remaining]
                was_clipped = len(content) > remaining
                tokens_est = len(clipped) // _READ_CONTEXT_CHARS_PER_TOKEN
                total_chars += len(clipped)
                files_out.append({
                    "path": str(abs_path.relative_to(workspace)).replace("\\", "/"),
                    "content": clipped,
                    "lines_read": clipped.count("\n") + 1,
                    "tokens_estimate": tokens_est,
                    "truncated": was_clipped,
                    "purpose": "context",
                })
                if was_clipped:
                    truncated = True
            except Exception:
                continue

        return {
            "ok": True,
            "files": files_out,
            "total_files_read": len(files_out),
            "total_tokens_estimate": total_chars // _READ_CONTEXT_CHARS_PER_TOKEN,
            "token_budget": token_budget,
            "truncated": truncated,
            "provenance": [
                {"path": f["path"], "lines_read": f["lines_read"], "purpose": f["purpose"]}
                for f in files_out
            ],
        }

    tools.register_tool(
        ToolDefinition(
            name="read_context",
            description=(
                "Token-budgeted multi-file reader for planner/reviewer context. "
                "Reads one or more workspace files, respects a token budget, "
                "and returns file contents with provenance metadata. "
                "If no paths are given, auto-selects relevant files from the project index "
                "(requires index_project to have run first). "
                "Use this before generating code that touches multiple files."
            ),
            handler=read_context_handler,
            parameters={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "description": "Workspace-relative file paths to read. Omit to auto-select from project index.",
                        "items": {"type": "string"},
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural language query to rank relevant files from the project index",
                    },
                    "token_budget": {
                        "type": "integer",
                        "description": "Max tokens to return in total (default 8000, max 32000)",
                    },
                    "root_path": {"type": "string", "description": "Workspace root (default '.')"},
                },
            },
        )
    )

    # ── propose_wiring ────────────────────────────────────────────────────────

    def _detect_framework(workspace_path: Path) -> str:
        """Heuristically detect the primary frontend/backend framework."""
        pkg_paths = list(workspace_path.glob("**/package.json"))
        for pkg_path in pkg_paths:
            if any(p in _INDEX_IGNORE_DIRS for p in pkg_path.relative_to(workspace_path).parts):
                continue
            try:
                pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "react" in deps:
                    return "vite-react"
            except Exception:
                pass
        if (workspace_path / "harness").is_dir() or (workspace_path / "pyproject.toml").exists():
            return "fastapi"
        return "unknown"

    def _find_file_by_pattern(workspace_path: Path, *patterns: str) -> Path | None:
        """Return the first existing file matching any of the glob patterns."""
        for pat in patterns:
            for m in sorted(workspace_path.glob(pat)):
                if m.is_file():
                    return m
        return None

    def _infer_symbol_name(component_path: str) -> str:
        """Derive a PascalCase component/class name from a file path."""
        stem = Path(component_path).stem
        for sfx in (".page", ".view", ".component", ".screen", ".module"):
            if stem.lower().endswith(sfx):
                stem = stem[: -len(sfx)]
                break
        parts = re.split(r"[-_\s]+", stem)
        return "".join(p.capitalize() for p in parts if p)

    async def propose_wiring_handler(args: dict[str, Any]) -> dict[str, Any]:
        component_path = str(args.get("component_path") or "").strip()
        if not component_path:
            return {"ok": False, "error": "component_path is required"}
        framework_arg = str(args.get("framework") or "auto").strip().lower()
        component_name = (
            str(args.get("component_name") or "").strip() or _infer_symbol_name(component_path)
        )
        route_path_arg = str(args.get("route_path") or "").strip()
        root_raw = args.get("root_path") or "."
        workspace = _resolve_workspace_path(str(root_raw))
        framework = framework_arg if framework_arg != "auto" else _detect_framework(workspace)
        provenance: list[dict[str, str]] = []
        proposals: list[dict[str, Any]] = []

        if framework == "vite-react":
            router_file = _find_file_by_pattern(
                workspace,
                "src/App.tsx", "src/App.jsx",
                "frontend/src/App.tsx", "frontend/src/App.jsx",
                "src/router.tsx", "src/router.jsx",
                "frontend/src/router.tsx",
            )
            if router_file:
                try:
                    router_rel = str(router_file.relative_to(workspace)).replace("\\", "/")
                    comp_abs = (
                        Path(component_path).resolve()
                        if Path(component_path).is_absolute()
                        else workspace / component_path
                    )
                    rel_import = os.path.relpath(
                        comp_abs.with_suffix(""), router_file.parent
                    ).replace("\\", "/")
                    if not rel_import.startswith("."):
                        rel_import = "./" + rel_import
                    effective_route = route_path_arg or "/" + component_name.lower()
                    provenance.append({"path": router_rel, "purpose": "router_entry_file"})
                    proposals.append({
                        "file": router_rel,
                        "description": (
                            f"Import {component_name} and add a <Route> element in {router_rel}"
                        ),
                        "patch_type": "insert_import_and_route",
                        "component_name": component_name,
                        "import_line": f"import {{ {component_name} }} from '{rel_import}';",
                        "route_element": (
                            f'<Route path="{effective_route}" element={{<{component_name} />}} />'
                        ),
                        "manual_instruction": (
                            f"1. Add near imports in {router_rel}: "
                            f"import {{ {component_name} }} from '{rel_import}';\n"
                            f"2. Add inside your <Routes> block: "
                            f'<Route path="{effective_route}" element={{<{component_name} />}} />'
                        ),
                    })
                except Exception as exc:
                    proposals.append({
                        "file": "src/App.tsx",
                        "description": f"Could not resolve router file: {exc}",
                        "patch_type": "manual",
                    })

            barrel = _find_file_by_pattern(
                workspace,
                "src/index.ts", "src/index.tsx",
                "frontend/src/index.ts",
            )
            if barrel:
                try:
                    barrel_rel = str(barrel.relative_to(workspace)).replace("\\", "/")
                    comp_abs = (
                        Path(component_path).resolve()
                        if Path(component_path).is_absolute()
                        else workspace / component_path
                    )
                    rel_import = os.path.relpath(
                        comp_abs.with_suffix(""), barrel.parent
                    ).replace("\\", "/")
                    if not rel_import.startswith("."):
                        rel_import = "./" + rel_import
                    provenance.append({"path": barrel_rel, "purpose": "barrel_export_file"})
                    proposals.append({
                        "file": barrel_rel,
                        "description": f"Re-export {component_name} from barrel index",
                        "patch_type": "append_export",
                        "component_name": component_name,
                        "export_line": f"export {{ {component_name} }} from '{rel_import}';",
                        "manual_instruction": (
                            f"Append to {barrel_rel}: "
                            f"export {{ {component_name} }} from '{rel_import}';"
                        ),
                    })
                except Exception:
                    pass

        elif framework == "fastapi":
            main_file = _find_file_by_pattern(
                workspace,
                "harness/api/server.py", "app/main.py", "main.py", "app/app.py",
            )
            rel_component = component_path.replace("\\", "/")
            module_dotpath = Path(rel_component).with_suffix("").as_posix().replace("/", ".")
            router_varname = Path(rel_component).stem.lower() + "_router"
            if main_file:
                main_rel = str(main_file.relative_to(workspace)).replace("\\", "/")
                provenance.append({"path": main_rel, "purpose": "fastapi_app_entry"})
                proposals.append({
                    "file": main_rel,
                    "description": (
                        f"Import {router_varname} from {module_dotpath} "
                        f"and register with app.include_router()"
                    ),
                    "patch_type": "insert_router",
                    "component_name": component_name,
                    "import_line": f"from {module_dotpath} import router as {router_varname}",
                    "include_line": (
                        f'app.include_router({router_varname}, '
                        f'prefix="/{Path(rel_component).stem.lower()}")'
                    ),
                    "manual_instruction": (
                        f"1. Add near imports in {main_rel}: "
                        f"from {module_dotpath} import router as {router_varname}\n"
                        f"2. After app is created: "
                        f'app.include_router({router_varname}, '
                        f'prefix="/{Path(rel_component).stem.lower()}")'
                    ),
                })
        else:
            proposals.append({
                "file": component_path,
                "description": f"Unknown framework '{framework}' — manual wiring required.",
                "patch_type": "manual",
                "manual_instruction": (
                    "Add this file to your app's routing or module registry manually."
                ),
            })

        provenance.append({"path": component_path, "purpose": "component_being_wired"})
        return {
            "ok": True,
            "framework": framework,
            "component_name": component_name,
            "component_path": component_path,
            "proposals": proposals,
            "provenance": provenance,
            "note": (
                "Use apply_wiring to automatically apply these proposals, "
                "or follow manual_instruction for each."
            ),
        }

    tools.register_tool(
        ToolDefinition(
            name="propose_wiring",
            description=(
                "Analyse the project structure and propose the minimal wiring changes needed "
                "to register a new component, route, or router module into the app entry point. "
                "Supports vite-react (App.tsx routing) and fastapi (include_router). "
                "Returns structured proposals with manual_instruction for each change "
                "and provenance of source files used. Run apply_wiring to execute the proposals."
            ),
            handler=propose_wiring_handler,
            parameters={
                "type": "object",
                "properties": {
                    "component_path": {
                        "type": "string",
                        "description": "Workspace-relative path of the new component/router file to wire in",
                    },
                    "framework": {
                        "type": "string",
                        "description": "vite-react | fastapi | auto (default auto)",
                    },
                    "component_name": {
                        "type": "string",
                        "description": "Symbol name override (default: derived from filename)",
                    },
                    "route_path": {
                        "type": "string",
                        "description": "URL path for the new route (e.g. /dashboard). Defaults to /componentname",
                    },
                    "root_path": {"type": "string", "description": "Workspace root (default '.')"},
                },
                "required": ["component_path"],
            },
        )
    )

    # ── apply_wiring ──────────────────────────────────────────────────────────

    async def apply_wiring_handler(args: dict[str, Any]) -> dict[str, Any]:
        proposals = args.get("proposals")
        if not isinstance(proposals, list) or not proposals:
            return {"ok": False, "error": "proposals must be a non-empty list (output of propose_wiring)"}
        dry_run = bool(args.get("dry_run", False))
        root_raw = args.get("root_path") or "."
        workspace = _resolve_workspace_path(str(root_raw))

        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        updated_paths: list[str] = []
        patch_summaries: list[str] = []

        for proposal in proposals:
            if not isinstance(proposal, dict):
                skipped.append({"proposal": str(proposal), "reason": "not a dict"})
                continue
            patch_type = str(proposal.get("patch_type") or "manual")
            target_file = str(proposal.get("file") or "").strip()
            if not target_file:
                skipped.append({"proposal": str(proposal), "reason": "no file specified"})
                continue
            target_path = (
                Path(target_file).resolve()
                if Path(target_file).is_absolute()
                else workspace / target_file
            )
            if patch_type == "manual":
                skipped.append({
                    "file": target_file,
                    "reason": "manual patch_type — requires human action",
                    "instruction": proposal.get("manual_instruction", ""),
                })
                continue
            if not target_path.is_file():
                skipped.append({"file": target_file, "reason": "target file does not exist"})
                continue
            try:
                current = target_path.read_text(encoding="utf-8")
            except Exception as exc:
                skipped.append({"file": target_file, "reason": f"read error: {exc}"})
                continue

            updated = current
            cname = str(proposal.get("component_name") or "")

            if patch_type == "insert_import_and_route":
                import_line = str(proposal.get("import_line") or "")
                route_element = str(proposal.get("route_element") or "")
                if import_line and import_line not in updated:
                    last_pos = max(updated.rfind("\nimport "), updated.rfind("\nfrom "))
                    if last_pos >= 0:
                        eol = updated.find("\n", last_pos + 1)
                        insert_at = eol + 1 if eol >= 0 else len(updated)
                    else:
                        insert_at = 0
                    updated = updated[:insert_at] + import_line + "\n" + updated[insert_at:]
                if route_element and route_element not in updated:
                    for closing_tag in ("</Routes>", "</Switch>"):
                        pos = updated.rfind(closing_tag)
                        if pos >= 0:
                            line_start = updated.rfind("\n", 0, pos) + 1
                            indent = ""
                            for ch in updated[line_start:pos]:
                                if ch in (" ", "\t"):
                                    indent += ch
                                else:
                                    break
                            updated = (
                                updated[:pos]
                                + indent + "  " + route_element + "\n"
                                + updated[pos:]
                            )
                            break

            elif patch_type == "append_export":
                export_line = str(proposal.get("export_line") or "")
                if export_line and export_line not in updated:
                    updated = updated.rstrip("\n") + "\n" + export_line + "\n"

            elif patch_type == "insert_router":
                import_line = str(proposal.get("import_line") or "")
                include_line = str(proposal.get("include_line") or "")
                if import_line and import_line not in updated:
                    last_pos = max(updated.rfind("\nimport "), updated.rfind("\nfrom "))
                    if last_pos >= 0:
                        eol = updated.find("\n", last_pos + 1)
                        insert_at = eol + 1 if eol >= 0 else len(updated)
                    else:
                        insert_at = 0
                    updated = updated[:insert_at] + import_line + "\n" + updated[insert_at:]
                if include_line and include_line not in updated:
                    for anchor in ("app = FastAPI", "app = APIRouter", "app.include_router"):
                        pos = updated.rfind(anchor)
                        if pos >= 0:
                            eol = updated.find("\n", pos)
                            insert_at = eol + 1 if eol >= 0 else len(updated)
                            updated = updated[:insert_at] + include_line + "\n" + updated[insert_at:]
                            break
                    else:
                        updated = updated.rstrip("\n") + "\n" + include_line + "\n"

            else:
                skipped.append({"file": target_file, "reason": f"unknown patch_type: {patch_type}"})
                continue

            if updated != current:
                if not dry_run:
                    target_path.write_text(updated, encoding="utf-8")
                applied.append({"file": target_file, "patch_type": patch_type, "dry_run": dry_run})
                updated_paths.append(str(target_path))
                patch_summaries.append(
                    f"Wired {cname or target_file} into {target_file} ({patch_type})"
                )
            else:
                skipped.append({"file": target_file, "reason": "no changes needed (already wired)"})

        return {
            "ok": True,
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "applied": applied,
            "skipped": skipped,
            "updated_paths": list(dict.fromkeys(updated_paths)),
            "patch_summaries": patch_summaries,
            "dry_run": dry_run,
        }

    tools.register_tool(
        ToolDefinition(
            name="apply_wiring",
            description=(
                "Apply the proposals returned by propose_wiring. "
                "Modifies target files in-place: inserts import statements, adds route elements, "
                "registers FastAPI routers, and appends barrel exports. "
                "Supports dry_run to preview changes without writing. "
                "Returns applied/skipped counts, updated_paths, and patch_summaries."
            ),
            handler=apply_wiring_handler,
            parameters={
                "type": "object",
                "properties": {
                    "proposals": {
                        "type": "array",
                        "description": "List of proposal objects from propose_wiring (or manually constructed)",
                        "items": {"type": "object"},
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview changes without writing files (default false)",
                    },
                    "root_path": {"type": "string", "description": "Workspace root (default '.')"},
                },
                "required": ["proposals"],
            },
        )
    )

    async def web_fetch_handler(args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url", "")).strip()
        if not url:
            raise ValueError("url is required")

        timeout_s = float(args.get("timeout_s", 10.0))
        max_chars = int(args.get("max_chars", 8000))

        verify = bool(args.get("verify_tls", True))
        try:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True, verify=verify) as client:
                response = await client.get(url)
                response.raise_for_status()
                body = response.text
        except Exception as exc:
            # Common local Windows cert-chain issue; retry with TLS verify disabled.
            msg = str(exc).lower()
            if "certificate verify failed" not in msg:
                raise
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True, verify=False) as client:
                response = await client.get(url)
                response.raise_for_status()
                body = response.text

        # Minimal HTML cleanup into readable plain text.
        body = re.sub(r"(?is)<script.*?>.*?</script>", " ", body)
        body = re.sub(r"(?is)<style.*?>.*?</style>", " ", body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()

        return {
            "ok": True,
            "url": str(response.url),
            "status_code": response.status_code,
            "content": body[:max_chars],
            "truncated": len(body) > max_chars,
        }

    tools.register_tool(
        ToolDefinition(
            name="web_fetch",
            description="Fetch the plain-text content of a URL for summarisation or research. Use this whenever the user asks about live data, current events, websites, news, prices, or anything requiring information from the web.",
            needs_network=True,
            handler=web_fetch_handler,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch (must start with http:// or https://)"},
                    "max_chars": {"type": "integer", "description": "Maximum characters to return (default 8000)"},
                },
                "required": ["url"],
            },
        )
    )

    async def web_browse_handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright  # type: ignore[import]
        except ImportError:
            return {"ok": False, "error": "playwright is not installed. Run: pip install playwright && playwright install chromium"}

        url = str(args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "url must start with http:// or https://"}

        selector = str(args.get("selector") or "").strip() or None
        wait_for = str(args.get("wait_for") or "load")
        timeout_ms = int(args.get("timeout_ms", 30000))
        max_chars = int(args.get("max_chars", 12000))
        screenshot = bool(args.get("screenshot", False))

        screenshot_path: str | None = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                )

                target_url = url
                try:
                    await page.goto(target_url, wait_until=wait_for, timeout=timeout_ms)
                except Exception as first_exc:
                    # Reddit sometimes blocks strict headless access; retry with old.reddit.com.
                    if "reddit.com" in url and "old.reddit.com" not in url:
                        fallback_url = (
                            url.replace("://www.reddit.com", "://old.reddit.com")
                            .replace("://reddit.com", "://old.reddit.com")
                        )
                        await page.goto(fallback_url, wait_until="domcontentloaded", timeout=timeout_ms)
                        target_url = fallback_url
                    else:
                        raise first_exc

                if selector:
                    await page.wait_for_selector(selector, timeout=timeout_ms)

                if screenshot:
                    import tempfile
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    screenshot_path = tmp.name
                    tmp.close()
                    await page.screenshot(path=screenshot_path, full_page=False)

                content = await page.inner_text("body")
                content = re.sub(r"\s+", " ", content).strip()
                final_url = page.url or target_url
                await browser.close()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "url": url}

        return {
            "ok": True,
            "url": url,
            "final_url": final_url,
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
            "screenshot_path": screenshot_path,
        }

    tools.register_tool(
        ToolDefinition(
            name="web_browse",
            description=(
                "Browse a URL using a real headless Chromium browser (Playwright). "
                "Use this for JavaScript-heavy pages, SPAs, or when web_fetch returns empty/broken content. "
                "Returns the visible page text after JS execution. Optionally waits for a CSS selector and captures a screenshot."
            ),
            needs_network=True,
            capabilities=["browser.chromium", "js.execute", "web.scrape", "screenshot"],
            handler=web_browse_handler,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to navigate to (http:// or https://)"},
                    "selector": {"type": "string", "description": "Optional CSS selector to wait for before extracting content"},
                    "wait_for": {"type": "string", "description": "Page load event to wait for: load (default), domcontentloaded, networkidle"},
                    "timeout_ms": {"type": "integer", "description": "Navigation timeout in milliseconds (default 30000)"},
                    "max_chars": {"type": "integer", "description": "Maximum characters of page text to return (default 12000)"},
                    "screenshot": {"type": "boolean", "description": "Whether to capture a PNG screenshot (default false)"},
                },
                "required": ["url"],
            },
        )
    )

    async def get_location_handler(args: dict[str, Any]) -> dict[str, Any]:
        """Return approximate geolocation of the server's public IP using ip-api.com (free, no key)."""
        timeout_s = float(args.get("timeout_s", 8))
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get("http://ip-api.com/json/?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,query")
            data = resp.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        if data.get("status") != "success":
            return {"ok": False, "error": data.get("message", "ip-api.com returned non-success status"), "raw": data}

        return {
            "ok": True,
            "ip": data.get("query"),
            "city": data.get("city"),
            "region": data.get("regionName"),
            "country": data.get("country"),
            "zip": data.get("zip"),
            "latitude": data.get("lat"),
            "longitude": data.get("lon"),
            "timezone": data.get("timezone"),
            "isp": data.get("isp"),
        }

    tools.register_tool(
        ToolDefinition(
            name="get_location",
            description=(
                "Return the approximate geographic location (city, region, country, lat/lon, timezone) "
                "of the server's public IP address. Uses ip-api.com — no API key required. "
                "Useful when the user asks 'where am I', 'what city am I in', or wants weather for their current location."
            ),
            needs_network=True,
            capabilities=["geo.ip", "location.city", "location.country"],
            handler=get_location_handler,
            parameters={
                "type": "object",
                "properties": {
                    "timeout_s": {"type": "number", "description": "Request timeout in seconds (default 8)"},
                },
                "required": [],
            },
        )
    )
