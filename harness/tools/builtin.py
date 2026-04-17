from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
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
        output_path = str(args.get("output_path", f"RELEASE_NOTES_{version}.md")).strip()
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

    async def read_file_handler(args: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(args.get("path") or args.get("target_path") or "").strip()
        if not raw_path:
            raise ValueError("path is required")
        target = _resolve_workspace_path(raw_path)
        if not target.exists() or not target.is_file():
            raise ValueError(f"file not found: {target}")
        max_chars = int(args.get("max_chars", 12000))
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "ok": True,
            "path": str(target).replace("\\", "/"),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    tools.register_tool(
        ToolDefinition(
            name="read_file",
            description="Read a text file from the allowed workspace. Use this before edits to inspect existing content.",
            handler=read_file_handler,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root or absolute allowed path"},
                    "max_chars": {"type": "integer", "description": "Max characters to return (default 12000)"},
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
