from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse
from typing import Any, AsyncIterator

from harness.api.hooks import ApiHooks
from harness.api.hooks import HookPayload
from harness.model.adapter import ModelRegistry, ModelRequest, ToolCall
from harness.runtime.config import ConfigManager
from harness.runtime.types import Task, TaskResult
from harness.tools.registry import ToolRegistry
from harness.skills.registry import SkillRegistry


class ReactiveStateMachine:
    """Agentic tool-calling loop: LLM decides which tools to use, the loop executes them
    and feeds results back until the model returns a final text response."""

    def __init__(
        self,
        models: ModelRegistry,
        config: ConfigManager,
        tools: ToolRegistry,
        skills: SkillRegistry = None,
        hooks: ApiHooks | None = None,
    ) -> None:
        self.models = models
        self.config = config
        self.tools = tools
        self.skills = skills
        self.hooks = hooks

    def _normalize_tool_call(self, tool_call: ToolCall, task_description: str) -> ToolCall:
        name = tool_call.name.strip()
        args = dict(tool_call.arguments)

        aliases: dict[str, str] = {
            "web_search_basic": "web_fetch",
            "web_search": "web_fetch",
            "search_web": "web_fetch",
            "browser_search": "web_fetch",
            "web.browse": "web_browse",
            "browser": "web_browse",
            "browse_web": "web_browse",
            "file_write": "write_file",
            "write_workspace_file": "write_file",
            "save_file": "write_file",
            "mkdir": "create_directory",
            "create_folder": "create_directory",
            "list_files": "list_directory",
            "ls": "list_directory",
        }
        normalized = aliases.get(name, name)
        normalized = self._resolve_registered_tool_name(normalized)

        task_text = task_description.lower()
        web_intent = any(token in task_text for token in ["weather", "search", "news", "price", "web", "internet", "current"]) 

        if normalized == "web_fetch":
            if "url" not in args:
                query = str(args.get("query") or args.get("q") or "").strip()
                if query:
                    args["url"] = f"https://duckduckgo.com/html/?q={quote_plus(query)}"

            url = str(args.get("url", "")).strip()
            if url and not url.startswith(("http://", "https://")):
                args["url"] = f"https://{url.lstrip('/')}"

            # Reddit homepage often returns anti-bot verification pages.
            # Normalize root requests to the public JSON feed for fast, reliable first-post extraction.
            normalized_url = str(args.get("url", "")).strip()
            if normalized_url:
                parsed = urlparse(normalized_url)
                host = (parsed.netloc or "").lower()
                path = (parsed.path or "").strip()
                if host.endswith("reddit.com") and path in {"", "/"}:
                    args["url"] = "https://www.reddit.com/r/all/.json?limit=1"

        if normalized == "shell_command" and web_intent:
            command = str(args.get("command", "")).strip()
            query = command or task_description
            return ToolCall(
                id=tool_call.id,
                name="web_fetch",
                arguments={"url": f"https://duckduckgo.com/html/?q={quote_plus(query)}"},
            )

        return ToolCall(id=tool_call.id, name=normalized, arguments=args)

    @staticmethod
    def _canonical_tool_name(name: str) -> str:
        return name.strip().lower().replace("-", "_").replace(".", "_").replace(":", "_")

    def _resolve_registered_tool_name(self, name: str) -> str:
        if self.tools.get_tool(name) is not None:
            return name
        canonical = self._canonical_tool_name(name)
        for tool in self.tools.list_tools():
            if self._canonical_tool_name(tool.name) == canonical:
                return tool.name
        return name

    def _is_skill_like_pseudo_call(self, tool_call: ToolCall) -> bool:
        if self.skills is None:
            return False

        normalized_name = tool_call.name.strip().lower()
        skill_ids = [skill.skill_id.replace('-', '_').lower() for skill in self.skills.list_skills()]
        if normalized_name in skill_ids:
            return True
        return any(skill_id in normalized_name for skill_id in skill_ids)

    def _detect_requested_tools(self, task_description: str) -> list[str]:
        """Detect explicitly requested tools from user task text."""
        text = task_description.lower()
        available = [tool.name for tool in self.tools.list_tools()]
        matched: set[str] = set()

        for tool_name in available:
            if tool_name.lower() in text:
                matched.add(tool_name)
            elif tool_name.startswith("repo_"):
                # Detect repo_* tools by their identifier (the word between "repo_" and the
                # first separator), e.g. "repo_playwright-browser_http_request" → "playwright".
                bare = tool_name[5:]  # strip "repo_"
                identifier = bare.split("-")[0].split("_")[0].lower()
                if identifier and len(identifier) >= 3 and identifier in text:
                    matched.add(tool_name)

        # Heuristic intent mapping for common user phrasing that omits exact tool names.
        if any(token in text for token in ["browser", "browse", "open website", "open the site", "navigate to"]):
            if "web_browse" in available:
                matched.add("web_browse")

        if any(token in text for token in ["list files", "list the files", "check files", "show files"]):
            if "list_directory" in available:
                matched.add("list_directory")

        # File-operation intent mapping for natural phrasing.
        if any(token in text for token in ["append a new line", "append new line", "append a line", "append to "]):
            if "append_file" in available:
                matched.add("append_file")
        if any(token in text for token in ["read_file", "read the file", "open the file", "return the full final file content"]):
            if "read_file" in available:
                matched.add("read_file")
        if any(token in text for token in ["create one", "create it", "create a file", "if you don't see", "if it does not exist"]):
            if "write_file" in available:
                matched.add("write_file")

        # Generic website retrieval should prefer fast fetch unless browser UI is explicit.
        if ("go to " in text or "open " in text) and ".com" in text:
            if "web_fetch" in available:
                matched.add("web_fetch")
            elif "web_browse" in available:
                matched.add("web_browse")

        return sorted(matched)

    def _detect_mandatory_tools(self, task_description: str) -> list[str]:
        """Detect tools that the user explicitly instructed with 'use <tool>' phrasing."""
        text = task_description.lower()
        available = [tool.name for tool in self.tools.list_tools()]
        mandatory: set[str] = set()

        for tool_name in available:
            lower_name = tool_name.lower()
            # Explicit imperative patterns from user text.
            if f"use {lower_name}" in text or f"use the {lower_name}" in text or f"{lower_name} tool" in text:
                mandatory.add(tool_name)

        # Common alias phrasing that should map to concrete tools.
        alias_map = {
            "web_browse": ["use browser", "use the browser", "browser tool"],
            "append_file": ["use append_file_tool", "append_file_tool", "append file tool"],
            "read_file": ["use read_file_tool", "read_file_tool", "read file tool"],
            "write_file": ["use write_file_tool", "write_file_tool", "write file tool"],
        }
        for tool_name, aliases in alias_map.items():
            if tool_name in available and any(alias in text for alias in aliases):
                mandatory.add(tool_name)

        # Enforce natural-language file mutation intents as mandatory operations.
        if any(token in text for token in ["append a new line", "append new line", "append a line", "append to "]):
            if "append_file" in available:
                mandatory.add("append_file")
        if any(token in text for token in ["read the file", "open the file", "return the full final file content", "use read_file"]):
            if "read_file" in available:
                mandatory.add("read_file")
        if any(token in text for token in ["create a file named", "create file named", "must create", "use write_file", "write_file tool"]):
            if "write_file" in available:
                mandatory.add("write_file")

        # Only require browser automation when UI navigation is explicitly requested.
        if any(token in text for token in ["use browser", "browser tool", "visually", "screenshot", "click", "scroll"]):
            if "web_browse" in available:
                mandatory.add("web_browse")
            elif "web_fetch" in available:
                mandatory.add("web_fetch")

        if "list_files" in text and "list_directory" in available:
            mandatory.add("list_directory")

        return sorted(mandatory)

    def _build_active_tool_definitions(self, requested_tools: list[str], *, allow_support_tools: bool = True) -> list[dict[str, Any]]:
        """Build tool definitions, optionally narrowed when user explicitly requests tools."""
        all_defs = self._build_tool_definitions()
        if not requested_tools:
            return all_defs

        essential_support_tools = {
            "create_directory",
            "write_file",
            "append_file",
            "read_file",
        }
        support_tools = {
            "list_directory",
            "rename_or_move",
            "delete_file",
            "search_workspace",
        }
        enabled_support = essential_support_tools | (support_tools if allow_support_tools else set())
        requested = set(requested_tools)
        filtered = [
            td
            for td in all_defs
            if str(td.get("function", {}).get("name", "")) in requested
            or str(td.get("function", {}).get("name", "")) in enabled_support
        ]
        return filtered or all_defs

    def _extract_browser_proof(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(tool_result, dict):
            return None

        lower_name = tool_name.lower()
        final_url = None
        for key in ("final_url", "url", "current_url", "page_url"):
            value = tool_result.get(key)
            if isinstance(value, str) and value.strip():
                final_url = value.strip()
                break
        if not final_url:
            arg_url = tool_args.get("url")
            if isinstance(arg_url, str) and arg_url.strip():
                final_url = arg_url.strip()

        evidence = None
        for key in ("evidence_snippet", "content", "text", "summary", "excerpt"):
            value = tool_result.get(key)
            if isinstance(value, str) and value.strip():
                evidence = value.strip()
                break

        screenshot_metadata: dict[str, Any] = {}
        for key in ("screenshot_path", "screenshot_url", "screenshot_id"):
            if key in tool_result:
                screenshot_metadata[key] = tool_result.get(key)
        meta = tool_result.get("screenshot_metadata")
        if isinstance(meta, dict):
            screenshot_metadata.update(meta)

        is_browser_tool = lower_name == "web_fetch"
        if not is_browser_tool and not final_url and not evidence and not screenshot_metadata:
            return None

        proof: dict[str, Any] = {"tool_name": tool_name}
        if final_url:
            proof["final_url"] = final_url
        if evidence:
            proof["evidence_snippet"] = evidence[:600]
        if screenshot_metadata:
            proof["screenshot_metadata"] = screenshot_metadata
        return proof

    @staticmethod
    def _artifact_extension(path: Path, mime_type: str) -> str:
        suffix = path.suffix.lower().lstrip(".")
        if suffix:
            return suffix
        fallback = {
            "text/markdown": "md",
            "text/html": "html",
            "application/pdf": "pdf",
            "image/svg+xml": "svg",
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
        }
        return fallback.get(mime_type.lower(), "bin")

    @staticmethod
    def _normalize_artifact_id(raw: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw.lower())
        safe = safe.strip("-")
        return safe or "artifact"

    def _persist_tool_artifacts(
        self,
        *,
        task_id: str,
        tenant_id: str = "_system_",
        workspace_root: Path,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        raw_artifacts = tool_result.get("artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            return [], []

        safe_inline_mimes = {
            "text/markdown",
            "text/html",
            "application/pdf",
            "image/svg+xml",
            "image/png",
            "image/jpeg",
            "image/webp",
        }
        run_root = (
            (workspace_root / ".titantshift" / "artifacts" / task_id)
            if tenant_id == "_system_"
            else (workspace_root / ".titantshift" / "artifacts" / tenant_id / task_id)
        ).resolve()
        persisted: list[dict[str, Any]] = []
        created_paths: list[str] = []

        for index, row in enumerate(raw_artifacts):
            if not isinstance(row, dict):
                continue
            raw_path = str(row.get("path") or "").strip()
            if not raw_path:
                continue
            source_path = Path(raw_path)
            if not source_path.is_absolute():
                source_path = (workspace_root / source_path).resolve()
            if not source_path.exists() or not source_path.is_file():
                continue

            mime_type = str(row.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream"
            generated_id = str(row.get("artifact_id") or f"{tool_name}-{index + 1}")
            artifact_id = self._normalize_artifact_id(generated_id)
            artifact_dir = (run_root / artifact_id).resolve()
            artifact_dir.mkdir(parents=True, exist_ok=True)

            ext = self._artifact_extension(source_path, mime_type)
            output_path = (artifact_dir / f"output.{ext}").resolve()
            shutil.copy2(source_path, output_path)
            created_paths.append(str(output_path).replace("\\", "/"))

            inputs_path = (artifact_dir / "inputs.json").resolve()
            inputs_path.write_text(
                json.dumps(
                    {
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "source_artifact": row,
                    },
                    indent=2,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
            created_paths.append(str(inputs_path).replace("\\", "/"))

            preview: dict[str, Any] | None = None
            if mime_type.lower() in safe_inline_mimes:
                preview = {
                    "url": f"/artifacts/run/{task_id}/{artifact_id}/preview",
                    "safe_inline": True,
                }

            record: dict[str, Any] = {
                "artifact_id": artifact_id,
                "kind": str(row.get("kind") or "document"),
                "path": str(output_path).replace("\\", "/"),
                "mime_type": mime_type,
                "title": str(row.get("title") or artifact_id),
                "summary": str(row.get("summary") or "Generated artifact"),
                "generator": str(row.get("generator") or tool_name),
                "backend": str(row.get("backend") or "unknown"),
                "verified": bool(row.get("verified", False)),
                "provenance": {
                    **(row.get("provenance") if isinstance(row.get("provenance"), dict) else {}),
                    "task_id": task_id,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
                "preview": preview,
            }
            artifact_meta_path = (artifact_dir / "artifact.json").resolve()
            artifact_meta_path.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
            created_paths.append(str(artifact_meta_path).replace("\\", "/"))
            persisted.append(record)
            if self.hooks is not None:
                try:
                    asyncio.get_running_loop().create_task(
                        self.hooks.emit(
                            HookPayload(
                                event="ArtifactEmit",
                                data={
                                    "task_id": task_id,
                                    "tenant_id": tenant_id,
                                    "artifact_id": artifact_id,
                                    "kind": record["kind"],
                                    "path": record["path"],
                                    "mime_type": record["mime_type"],
                                    "title": record["title"],
                                    "generator": record["generator"],
                                },
                            )
                        )
                    )
                except RuntimeError:
                    pass

        return persisted, created_paths

    def _narrow_tools_by_skill_recommendation(
        self,
        all_tool_defs: list[dict[str, Any]],
        task_description: str,
    ) -> list[dict[str, Any]] | None:
        """Apply 3-stage filter to narrow tools based on skill recommendations.
        
        Returns narrowed tool list if successful filtering occurred, None if no narrowing applied.
        
        The filter stages are:
        1. Exact Skill Match: Use skill.required_tools directly
        2. Keyword Surface Match: Match tool capabilities and names semantically
        3. Semantic Description Match: Use LLM to match descriptions (future enhancement)
        """
        if not self.skills:
            return None

        task_lower = task_description.lower()
        narrowed_tools: set[str] = set()
        
        # Stage 1: Exact skill match from required_tools
        for skill in self.skills.list_skills():
            if skill.required_tools:
                skill_matches_task = (
                    skill.skill_id.lower() in task_lower
                    or skill.description.lower() in task_lower
                    or any(tag.lower() in task_lower for tag in skill.tags)
                )
                if skill_matches_task:
                    narrowed_tools.update(skill.required_tools)
        
        # Stage 2: Keyword surface match on tool capabilities and metadata
        task_keywords = set(task_lower.split())
        for tool_def in all_tool_defs:
            tool_name = str(tool_def.get("function", {}).get("name", "")).lower()
            tool_desc = str(tool_def.get("function", {}).get("description", "")).lower()
            capabilities = tool_def.get("capabilities", []) if isinstance(tool_def, dict) else []
            
            # Convert capabilities to a searchable string
            caps_str = " ".join([str(c).lower() for c in (capabilities or [])])
            
            # Match domain/domain keywords
            matches_intent = False
            
            # Direct capability matches
            for keyword in task_keywords:
                if len(keyword) > 3:  # Skip common words
                    if keyword in tool_name or keyword in tool_desc or keyword in caps_str:
                        matches_intent = True
                        break
            
            # Common intent patterns
            if not matches_intent:
                intent_patterns = {
                    "search": {"web_fetch", "repo_", "http"},
                    "browse": {"web_fetch", "browser"},
                    "api": {"http", "repo_"},
                    "data": {"read_file", "search_workspace"},
                    "file": {"write_file", "create_directory", "read_file"},
                    "code": {"write_file", "shell_command"},
            }
                for intent, tool_hints in intent_patterns.items():
                    if intent in task_lower:
                        if any(hint in tool_name or hint in caps_str for hint in tool_hints):
                            matches_intent = True
                            break
            
            if matches_intent:
                narrowed_tools.add(tool_name)
        
        # If we found narrowed tools, return only those
        if narrowed_tools:
            filtered = [
                td for td in all_tool_defs
                if str(td.get("function", {}).get("name", "")).lower() in narrowed_tools
            ]
            if filtered:
                return filtered
        
        # Stage 3: Fallback - return all tools if narrowing didn't reduce the set meaningfully
        # (This is where semantic LLM matching would go in future)
        return None

    async def run_task(self, task: Task) -> TaskResult:
        budget = self._resolve_budget(task)
        if budget["max_steps"] < 1:
            return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: max_steps < 1")

        preferred_backend = task.input.get("model_backend") if task.input else None
        workspace_root = task.input.get("workspace_root") if task.input else None
        model = self.models.select_model(preferred_backend)

        # System prompt
        requested_tools = self._detect_requested_tools(task.description)
        mandatory_tools = self._detect_mandatory_tools(task.description)
        requested_canonical = {self._canonical_tool_name(name) for name in requested_tools}
        mandatory_canonical = {self._canonical_tool_name(name) for name in mandatory_tools}
        requested_repo_tools = [name for name in requested_tools if name.startswith("repo_")]
        system_parts = [
            "You are a helpful AI assistant integrated into the TitanShift agent harness.",
            "When you need live information, use the most specific available tool for the user request. "
            "Use web_fetch for general web lookups only when a specific requested tool is not required.",
            "When the user asks you to create or modify workspace files, use create_directory and write_file. "
            "Do not merely describe the files when you can create them.",
            "After completing file operations, summarize what was created and where. Do not paste full file contents "
            "unless the user explicitly asks to see the code.",
            "Only emit tool calls for actual tools from the provided tool schema. Never emit tool calls for skills "
            "such as brainstorming, writing-plans, or subagent-driven-development.",
        ]
        if requested_tools:
            system_parts.append(
                "The user explicitly requested these tools: "
                + ", ".join(requested_tools)
                + ". You must attempt these requested tools before substituting alternatives. "
                "Do not replace requested repo/browser tools with web_fetch unless requested tools fail."
            )
        if mandatory_tools:
            system_parts.append(
                "The user explicitly instructed these tools with imperative wording and they are mandatory to attempt: "
                + ", ".join(mandatory_tools)
                + ". Do not finalize until each mandatory tool has been attempted at least once."
            )
        if workspace_root:
            system_parts.append(
                f"The active workspace folder is: {workspace_root}. "
                "When creating or modifying files, use paths relative to this workspace."
            )

        # Inject available skills if skill registry is available
        if self.skills:
            workflow_mode = task.input.get("workflow_mode") if task.input else self.config.get("orchestrator.workflow_mode", "lightning")
            is_superpowered = str(workflow_mode).lower() == "superpowered"
            skills_section = self.skills.format_for_system_prompt(workflow_mode)
            if skills_section:
                system_parts.append("\n" + skills_section)

        system_prompt = " ".join(system_parts)

        # Build OpenAI-format tool definitions from the registry
        tool_defs = self._build_active_tool_definitions(requested_tools)
        
        # Apply 3-stage tool narrowing filter based on skill recommendations
        # This helps the model select relevant tools even when skill recommendations don't exactly match tool names
        narrowed_tools = self._narrow_tools_by_skill_recommendation(tool_defs, task.description)
        if narrowed_tools:
            tool_defs = narrowed_tools

        # Multi-turn message history
        conversation_history: list[dict[str, Any]] = task.input.get("conversation_history", []) if task.input else []
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        used_tools: list[str] = []
        tool_errors: list[str] = []
        last_tool_result_lines: list[str] = []
        browser_proofs: list[dict[str, Any]] = []
        test_failure_summary: list[str] = []
        test_failed_count: int | None = None
        patch_summaries: list[str] = []
        context_provenance: list[dict[str, Any]] = []
        created_paths: list[str] = []
        updated_paths: list[str] = []
        artifacts: list[dict[str, Any]] = []
        final_text = ""
        last_model_id = model.model_id
        total_tokens = model.estimate_tokens(task.description)
        response = None
        workspace_root_path = Path(str(workspace_root or ".")).resolve()
        tenant_id = str(task.input.get("tenant_id", "_system_")) if task.input else "_system_"
        allowed_tools = list(task.input.get("allowed_tools", [])) if task.input else []
        llm_call_index = 0

        # ── SessionStart hook ──────────────────────────────────────────────
        if self.hooks is not None:
            try:
                await self.hooks.emit(HookPayload(
                    event="SessionStart",
                    data={
                        "task_id": task.id,
                        "tenant_id": tenant_id,
                        "description": task.description,
                        "budget": budget,
                    },
                ))
            except Exception:
                pass

        # Prepend prior conversation turns so the model has full context
        for prior in conversation_history:
            role = prior.get("role", "user")
            content = prior.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
                total_tokens += model.estimate_tokens(content)

        messages.append({"role": "user", "content": task.description})

        for step in range(budget["max_steps"]):
            if total_tokens > budget["max_tokens"]:
                return TaskResult(
                    task_id=task.id,
                    output={"response": final_text, "mode": "reactive", "used_tools": used_tools},
                    success=False,
                    error="Budget exceeded: token limit reached",
                )

            try:
                used_requested_tools = [name for name in used_tools if self._canonical_tool_name(name) in requested_canonical]
                used_mandatory_tools = [name for name in used_tools if self._canonical_tool_name(name) in mandatory_canonical]
                active_tool_defs = None
                # If there are explicitly requested tools, narrow tool set until at least one is attempted.
                if requested_tools and not used_requested_tools:
                    active_tool_defs = self._build_active_tool_definitions(
                        requested_tools,
                        allow_support_tools=False,
                    )
                # If there are mandatory tools not yet attempted, keep model focused on mandatory set.
                if (not requested_tools or used_requested_tools) and mandatory_tools and len(used_mandatory_tools) < len(mandatory_tools):
                    active_tool_defs = self._build_active_tool_definitions(
                        mandatory_tools,
                        allow_support_tools=False,
                    )
                llm_messages = list(messages)
                if self.hooks is not None:
                    directives = await self.hooks.execute(
                        "PreLLMCall",
                        {
                            "task_id": task.id,
                            "tenant_id": tenant_id,
                            "model": model.model_id,
                            "messages": llm_messages,
                            "tools_schema": active_tool_defs or [],
                            "call_index": llm_call_index,
                        },
                    )
                    for directive in directives:
                        if not isinstance(directive, dict):
                            continue
                        if str(directive.get("action", "")).strip().lower() == "inject_message" and isinstance(directive.get("injected_message"), dict):
                            llm_messages = [directive["injected_message"], *llm_messages]
                max_duration_s: float | None = None
                if int(budget["max_duration_ms"]) > 0:
                    max_duration_s = budget["max_duration_ms"] / 1000.0
                model_timeout_s = float(getattr(model, "timeout_s", 45.0))
                effective_model_timeout = (
                    max(5.0, min(model_timeout_s, max_duration_s))
                    if max_duration_s is not None
                    else max(5.0, model_timeout_s)
                )
                model_req = ModelRequest(
                    prompt="",
                    system_prompt=system_prompt,
                    messages=llm_messages,
                    tool_definitions=active_tool_defs,
                    timeout_s=effective_model_timeout,
                )
                if max_duration_s is None:
                    response = await model.generate(model_req)
                else:
                    response = await asyncio.wait_for(
                        model.generate(model_req),
                        timeout=max_duration_s,
                    )
                if self.hooks is not None:
                    await self.hooks.emit(
                        HookPayload(
                            event="PostLLMCall",
                            data={
                                "task_id": task.id,
                                "tenant_id": tenant_id,
                                "model": response.model_id,
                                "response_text": response.text,
                                "tool_calls": [
                                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                    for tc in (response.tool_calls or [])
                                ],
                                "input_tokens": total_tokens,
                                "output_tokens": model.estimate_tokens(response.text),
                                "duration_ms": 0.0,
                                "call_index": llm_call_index,
                            },
                        )
                    )
                llm_call_index += 1
            except asyncio.TimeoutError:
                if last_tool_result_lines:
                    fallback = (
                        "Timed out while generating the final response, but tool results were collected:\n\n"
                        + "\n".join(last_tool_result_lines)
                    )
                    return TaskResult(
                        task_id=task.id,
                        output={
                            "response": fallback,
                            "model": last_model_id,
                            "mode": "reactive",
                            "estimated_total_tokens": total_tokens,
                            "used_tools": used_tools,
                        },
                        success=True,
                    )
                return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: task timeout")
            except RuntimeError as exc:
                if last_tool_result_lines and "timed out" in str(exc).lower():
                    fallback = (
                        "The model timed out while preparing the final write-up, but workspace/tool actions completed:\n\n"
                        + "\n".join(last_tool_result_lines)
                    )
                    return TaskResult(
                        task_id=task.id,
                        output={
                            "response": fallback,
                            "model": last_model_id,
                            "mode": "reactive",
                            "estimated_total_tokens": total_tokens,
                            "used_tools": used_tools,
                        },
                        success=True,
                    )
                raise

            last_model_id = response.model_id

            if not response.tool_calls:
                if mandatory_tools:
                    missing = [
                        name for name in mandatory_tools
                        if self._canonical_tool_name(name) not in {self._canonical_tool_name(t) for t in used_tools}
                    ]
                    if missing:
                        correction = (
                            "You must attempt all mandatory tools before finishing. Still missing: "
                            + ", ".join(missing)
                        )
                        messages.append({"role": "user", "content": correction})
                        total_tokens += model.estimate_tokens(correction)
                        continue
                if requested_tools and not any(self._canonical_tool_name(name) in requested_canonical for name in used_tools):
                    correction = (
                        "You must first attempt at least one explicitly requested tool before finishing. "
                        + "Requested tools: "
                        + ", ".join(requested_tools)
                    )
                    messages.append({"role": "user", "content": correction})
                    total_tokens += model.estimate_tokens(correction)
                    continue
                # LLM produced a final text answer — done
                final_text = response.text
                total_tokens += model.estimate_tokens(response.text)
                break

            # --- Execute tool calls and append results to history ---
            # LM Studio compatibility note: some model/server combos reject tool-role messages.
            # We therefore feed tool outputs back as plain user context for the next turn.
            tool_result_lines: list[str] = []
            normalized_tool_calls = [self._normalize_tool_call(raw_tc, task.description) for raw_tc in response.tool_calls]
            if requested_tools and not any(self._canonical_tool_name(name) in requested_canonical for name in used_tools):
                if not any(self._canonical_tool_name(tc.name) in requested_canonical for tc in normalized_tool_calls):
                    correction = (
                        "Support tools alone are insufficient here. Attempt at least one explicitly requested tool first: "
                        + ", ".join(requested_tools)
                    )
                    messages.append({"role": "user", "content": correction})
                    total_tokens += model.estimate_tokens(correction)
                    continue
            if (not requested_tools or any(self._canonical_tool_name(name) in requested_canonical for name in used_tools)) and mandatory_tools:
                missing = [
                    name for name in mandatory_tools
                    if self._canonical_tool_name(name) not in {self._canonical_tool_name(t) for t in used_tools}
                ]
                if missing and not any(self._canonical_tool_name(tc.name) in {self._canonical_tool_name(m) for m in missing} for tc in normalized_tool_calls):
                    correction = (
                        "You must call the remaining mandatory tools before other actions. Remaining: "
                        + ", ".join(missing)
                    )
                    messages.append({"role": "user", "content": correction})
                    total_tokens += model.estimate_tokens(correction)
                    continue

            for call_index, tc in enumerate(normalized_tool_calls):
                used_tools.append(tc.name)
                if self._is_skill_like_pseudo_call(tc):
                    tool_content = json.dumps(
                        {
                            "ok": True,
                            "skill_like_call": tc.name,
                            "note": (
                                "Skills are not callable tools. Use the skill guidance implicitly and "
                                "continue answering the user directly without emitting a skill call."
                            ),
                            "arguments": tc.arguments,
                        }
                    )
                    total_tokens += model.estimate_tokens(tool_content)
                    tool_result_lines.append(
                        f"Tool-like skill call `{tc.name}` with {json.dumps(tc.arguments)} was converted into guidance: {tool_content}"
                    )
                    continue
                # ── PreToolUse hook ───────────────────────────────────────
                if self.hooks is not None:
                    try:
                        await self.hooks.emit(HookPayload(
                            event="PreToolUse",
                            data={
                                "task_id": task.id,
                                "tenant_id": tenant_id,
                                "tool": tc.name,
                                "arguments": tc.arguments,
                                "step": step,
                                "call_index": call_index,
                            },
                        ))
                    except Exception:
                        pass

                try:
                    # Bypass policy checks in superpowered mode since it has approval gates
                    result = await self.tools.execute_tool(
                        tc.name,
                        tc.arguments,
                        bypass_policy=is_superpowered,
                        task_id=task.id,
                        hook_context={
                            "tenant_id": tenant_id,
                            "allowed_tools": allowed_tools,
                            "call_index": call_index,
                        },
                    )
                    tool_result: dict[str, Any] | Any = result
                except PermissionError as exc:
                    tool_errors.append(f"{tc.name}: {exc}")
                    if tc.name == "shell_command":
                        fallback_args = {
                            "url": f"https://duckduckgo.com/html/?q={quote_plus(task.description)}"
                        }
                        try:
                            fallback = await self.tools.execute_tool(
                                "web_fetch",
                                fallback_args,
                                bypass_policy=is_superpowered,
                                task_id=task.id,
                                hook_context={
                                    "tenant_id": tenant_id,
                                    "allowed_tools": allowed_tools,
                                    "call_index": call_index,
                                },
                            )
                            tool_result = {
                                "ok": True,
                                "fallback": "web_fetch",
                                "original_error": str(exc),
                                "result": fallback,
                            }
                        except Exception as fallback_exc:
                            tool_result = {
                                "ok": False,
                                "error": str(exc),
                                "fallback_error": str(fallback_exc),
                            }
                    else:
                        tool_result = {"ok": False, "error": str(exc)}
                except Exception as exc:
                    tool_errors.append(f"{tc.name}: {exc}")
                    tool_result = {"ok": False, "error": str(exc)}

                proof = self._extract_browser_proof(tc.name, tc.arguments, tool_result)
                if proof:
                    browser_proofs.append(proof)

                if isinstance(tool_result, dict):
                    created = tool_result.get("created_paths")
                    if isinstance(created, list):
                        created_paths.extend(str(path) for path in created if str(path).strip())
                    updated = tool_result.get("updated_paths")
                    if isinstance(updated, list):
                        updated_paths.extend(str(path) for path in updated if str(path).strip())
                    persisted_artifacts, artifact_created_paths = self._persist_tool_artifacts(
                        task_id=task.id,
                        tenant_id=tenant_id,
                        workspace_root=workspace_root_path,
                        tool_name=tc.name,
                        tool_args=tc.arguments,
                        tool_result=tool_result,
                    )
                    if persisted_artifacts:
                        artifacts.extend(persisted_artifacts)
                    if artifact_created_paths:
                        created_paths.extend(artifact_created_paths)

                if tc.name == "run_tests" and isinstance(tool_result, dict):
                    failure_rows = tool_result.get("failure_summary")
                    if isinstance(failure_rows, list):
                        test_failure_summary.extend(str(row).strip() for row in failure_rows if str(row).strip())
                    failed_count = tool_result.get("failed_count")
                    if isinstance(failed_count, int):
                        test_failed_count = max(test_failed_count or 0, failed_count)

                if tc.name == "patch_file" and isinstance(tool_result, dict):
                    summary = tool_result.get("patch_summary")
                    if summary and str(summary).strip():
                        patch_summaries.append(str(summary).strip())

                if tc.name == "read_context" and isinstance(tool_result, dict):
                    prov_items = tool_result.get("provenance")
                    if isinstance(prov_items, list):
                        context_provenance.extend(
                            item for item in prov_items if isinstance(item, dict)
                        )

                if tc.name == "apply_wiring" and isinstance(tool_result, dict):
                    wiring_summaries = tool_result.get("patch_summaries")
                    if isinstance(wiring_summaries, list):
                        patch_summaries.extend(
                            str(s).strip() for s in wiring_summaries if str(s).strip()
                        )
                    wiring_prov = tool_result.get("provenance")
                    if isinstance(wiring_prov, list):
                        context_provenance.extend(
                            item for item in wiring_prov if isinstance(item, dict)
                        )

                # ── PostToolUse hook ──────────────────────────────────────
                if self.hooks is not None:
                    try:
                        await self.hooks.emit(HookPayload(
                            event="PostToolUse",
                            data={
                                "task_id": task.id,
                                "tenant_id": tenant_id,
                                "tool": tc.name,
                                "arguments": tc.arguments,
                                "result": tool_result if isinstance(tool_result, dict) else {"raw": str(tool_result)},
                                "step": step,
                            },
                        ))
                    except Exception:
                        pass

                tool_content = json.dumps(tool_result, default=str)

                total_tokens += model.estimate_tokens(tool_content)
                condensed = tool_content[:2800]
                if len(tool_content) > 2800:
                    condensed += " ... [tool output truncated]"
                tool_result_lines.append(
                    f"Tool `{tc.name}` called with {json.dumps(tc.arguments)} returned: {condensed}"
                )
            last_tool_result_lines = tool_result_lines.copy()

            messages.append({
                "role": "user",
                "content": (
                    "Tool outputs are now available. Use them as primary evidence and answer the original request.\n"
                    + "\n".join(tool_result_lines)
                ),
            })
        else:
            # Loop exhausted without a break (no final text produced)
            if not final_text:
                final_text = "[Agent reached max steps without producing a final response]"

        used_requested = [name for name in used_tools if self._canonical_tool_name(name) in requested_canonical]
        missing_requested_tools = bool(requested_canonical) and not bool(used_requested)
        fallback_used = missing_requested_tools
        primary_failure_reason = None
        if tool_errors:
            primary_failure_reason = tool_errors[0]
        elif missing_requested_tools:
            primary_failure_reason = "Requested tools were not used by model output"

        deduped_test_summary: list[str] = []
        for row in test_failure_summary:
            if row not in deduped_test_summary:
                deduped_test_summary.append(row)

        latest_browser_proof = browser_proofs[-1] if browser_proofs else None
        deduped_created_paths = list(dict.fromkeys(created_paths))
        deduped_updated_paths = list(dict.fromkeys(updated_paths))
        deduped_artifacts: list[dict[str, Any]] = []
        seen_artifact_ids: set[str] = set()
        for artifact in artifacts:
            artifact_id = str(artifact.get("artifact_id") or "").strip()
            if artifact_id and artifact_id in seen_artifact_ids:
                continue
            if artifact_id:
                seen_artifact_ids.add(artifact_id)
            deduped_artifacts.append(artifact)

        # ── Stop hook ─────────────────────────────────────────────────────
        if self.hooks is not None:
            try:
                await self.hooks.emit(HookPayload(
                    event="Stop",
                    data={
                        "task_id": task.id,
                        "tenant_id": tenant_id,
                        "success": bool(final_text and not final_text.startswith("[Agent reached") and not missing_requested_tools),
                        "response": final_text,
                        "used_tools": used_tools,
                    },
                ))
            except Exception:
                pass

        return TaskResult(
            task_id=task.id,
            output={
                "response": final_text,
                "model": last_model_id,
                "mode": "reactive",
                "estimated_total_tokens": total_tokens,
                "used_tools": used_tools,
                "requested_tools": requested_tools,
                "attempted_tools": used_tools,
                "fallback_used": fallback_used,
                "primary_failure_reason": primary_failure_reason,
                "browser_proof": latest_browser_proof,
                "browser_proofs": browser_proofs,
                "test_failure_summary": deduped_test_summary[:20],
                "test_failed_count": test_failed_count,
                "created_paths": deduped_created_paths,
                "updated_paths": deduped_updated_paths,
                "patch_summaries": list(dict.fromkeys(patch_summaries)),
                "context_provenance": context_provenance,
                "artifacts": deduped_artifacts,
            },
            success=bool(final_text and not final_text.startswith("[Agent reached") and not missing_requested_tools),
        )

    # ── Streaming variant ─────────────────────────────────────────────────────

    async def run_task_stream(self, task: Task) -> AsyncIterator[dict[str, Any]]:
        """Run a task and yield SSE-style event dicts as execution progresses.

        Event types:
          start       — task accepted, budget resolved
          step        — model generated one or more tool calls (about to execute)
          tool_result — tool call finished
          text_delta  — model produced final text (emitted once)
          done        — task complete; includes full TaskResult fields
          error       — unrecoverable error
        """
        budget = self._resolve_budget(task)
        if budget["max_steps"] < 1:
            yield {"type": "error", "message": "Budget exceeded: max_steps < 1"}
            return

        yield {
            "type": "start",
            "task_id": task.id,
            "max_steps": budget["max_steps"],
            "max_tokens": budget["max_tokens"],
        }

        preferred_backend = task.input.get("model_backend") if task.input else None
        workspace_root = task.input.get("workspace_root") if task.input else None
        model = self.models.select_model(preferred_backend)

        requested_tools = self._detect_requested_tools(task.description)
        mandatory_tools = self._detect_mandatory_tools(task.description)
        requested_canonical = {self._canonical_tool_name(name) for name in requested_tools}
        mandatory_canonical = {self._canonical_tool_name(name) for name in mandatory_tools}
        system_parts = [
            "You are a helpful AI assistant integrated into the TitanShift agent harness.",
            "When you need live information, use the most specific available tool for the user request.",
            "When the user asks you to create or modify workspace files, use create_directory and write_file.",
            "After completing file operations, summarize what was created and where.",
            "Only emit tool calls for actual tools from the provided tool schema.",
        ]
        if requested_tools:
            system_parts.append(
                "The user explicitly requested these tools: "
                + ", ".join(requested_tools)
                + ". Attempt them before substituting alternatives."
            )
        if workspace_root:
            system_parts.append(
                f"The active workspace folder is: {workspace_root}. "
                "Use paths relative to this workspace."
            )
        if self.skills:
            workflow_mode = task.input.get("workflow_mode") if task.input else self.config.get("orchestrator.workflow_mode", "lightning")
            skills_section = self.skills.format_for_system_prompt(workflow_mode)
            if skills_section:
                system_parts.append("\n" + skills_section)

        system_prompt = " ".join(system_parts)
        tool_defs = self._build_active_tool_definitions(requested_tools)
        narrowed_tools = self._narrow_tools_by_skill_recommendation(tool_defs, task.description)
        if narrowed_tools:
            tool_defs = narrowed_tools

        conversation_history: list[dict[str, Any]] = task.input.get("conversation_history", []) if task.input else []
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for prior in conversation_history:
            role = prior.get("role", "user")
            content = prior.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": task.description})

        used_tools: list[str] = []
        tool_errors: list[str] = []
        created_paths: list[str] = []
        updated_paths: list[str] = []
        artifacts: list[dict[str, Any]] = []
        patch_summaries: list[str] = []
        context_provenance: list[dict[str, Any]] = []
        final_text = ""
        last_model_id = model.model_id
        total_tokens = model.estimate_tokens(task.description)
        workspace_root_path = Path(str(workspace_root or ".")).resolve()
        workflow_mode_str = str(task.input.get("workflow_mode", "lightning") if task.input else "lightning")
        is_superpowered = workflow_mode_str.lower() == "superpowered"
        tenant_id = str(task.input.get("tenant_id", "_system_")) if task.input else "_system_"
        allowed_tools = list(task.input.get("allowed_tools", [])) if task.input else []
        llm_call_index = 0
        last_diff: str = ""  # last patch/replace diff captured for PreviewPanel

        # ── SessionStart hook ──────────────────────────────────────────────
        if self.hooks is not None:
            try:
                await self.hooks.emit(HookPayload(
                    event="SessionStart",
                    data={
                        "task_id": task.id,
                        "tenant_id": tenant_id,
                        "description": task.description,
                        "budget": budget,
                    },
                ))
            except Exception:
                pass

        try:
            for step in range(budget["max_steps"]):
                if total_tokens > budget["max_tokens"]:
                    yield {"type": "error", "message": "Budget exceeded: token limit reached"}
                    return

                try:
                    used_requested_tools = [n for n in used_tools if self._canonical_tool_name(n) in requested_canonical]
                    used_mandatory_tools = [n for n in used_tools if self._canonical_tool_name(n) in mandatory_canonical]
                    active_tool_defs = None
                    if requested_tools and not used_requested_tools:
                        active_tool_defs = self._build_active_tool_definitions(requested_tools, allow_support_tools=False)
                    if (not requested_tools or used_requested_tools) and mandatory_tools and len(used_mandatory_tools) < len(mandatory_tools):
                        active_tool_defs = self._build_active_tool_definitions(mandatory_tools, allow_support_tools=False)
                    llm_messages = list(messages)
                    if self.hooks is not None:
                        directives = await self.hooks.execute(
                            "PreLLMCall",
                            {
                                "task_id": task.id,
                                "tenant_id": tenant_id,
                                "model": model.model_id,
                                "messages": llm_messages,
                                "tools_schema": active_tool_defs or [],
                                "call_index": llm_call_index,
                            },
                        )
                        for directive in directives:
                            if not isinstance(directive, dict):
                                continue
                            if str(directive.get("action", "")).strip().lower() == "inject_message" and isinstance(directive.get("injected_message"), dict):
                                llm_messages = [directive["injected_message"], *llm_messages]
                    max_duration_s: float | None = None
                    if int(budget["max_duration_ms"]) > 0:
                        max_duration_s = budget["max_duration_ms"] / 1000.0
                    model_timeout_s = float(getattr(model, "timeout_s", 45.0))
                    effective_model_timeout = (
                        max(5.0, min(model_timeout_s, max_duration_s))
                        if max_duration_s is not None
                        else max(5.0, model_timeout_s)
                    )
                    model_req = ModelRequest(
                        prompt="",
                        system_prompt=system_prompt,
                        messages=llm_messages,
                        tool_definitions=active_tool_defs,
                        timeout_s=effective_model_timeout,
                    )
                    if max_duration_s is None:
                        response = await model.generate(model_req)
                    else:
                        response = await asyncio.wait_for(
                            model.generate(model_req),
                            timeout=max_duration_s,
                        )
                    if self.hooks is not None:
                        await self.hooks.emit(
                            HookPayload(
                                event="PostLLMCall",
                                data={
                                    "task_id": task.id,
                                    "tenant_id": tenant_id,
                                    "model": response.model_id,
                                    "response_text": response.text,
                                    "tool_calls": [
                                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                        for tc in (response.tool_calls or [])
                                    ],
                                    "input_tokens": total_tokens,
                                    "output_tokens": model.estimate_tokens(response.text),
                                    "duration_ms": 0.0,
                                    "call_index": llm_call_index,
                                },
                            )
                        )
                    llm_call_index += 1
                except (asyncio.TimeoutError, RuntimeError):
                    yield {"type": "error", "message": "Model timed out"}
                    return

                last_model_id = response.model_id

                if not response.tool_calls:
                    final_text = response.text
                    total_tokens += model.estimate_tokens(response.text)
                    yield {"type": "text_delta", "step": step, "text": final_text}
                    break

                # Emit step event listing the tool calls about to execute
                yield {
                    "type": "step",
                    "step": step,
                    "tool_calls": [
                        {"tool": tc.name, "args": tc.arguments}
                        for tc in self._normalize_calls_for_stream(response.tool_calls)
                    ],
                }

                tool_result_lines: list[str] = []
                for call_index, tc in enumerate(self._normalize_calls_for_stream(response.tool_calls)):
                    used_tools.append(tc.name)
                    if self._is_skill_like_pseudo_call(tc):
                        tool_content = json.dumps({"ok": True, "skill_like_call": tc.name})
                        total_tokens += model.estimate_tokens(tool_content)
                        tool_result_lines.append(f"Tool `{tc.name}` returned: {tool_content}")
                        yield {"type": "tool_result", "step": step, "tool": tc.name, "ok": True, "summary": "skill-like call redirected"}
                        continue
                    # ── PreToolUse hook ──────────────────────────────────────
                    if self.hooks is not None:
                        try:
                            await self.hooks.emit(HookPayload(
                                event="PreToolUse",
                                data={
                                    "task_id": task.id,
                                    "tenant_id": tenant_id,
                                    "tool": tc.name,
                                    "arguments": tc.arguments,
                                    "step": step,
                                    "call_index": call_index,
                                },
                            ))
                        except Exception:
                            pass

                    try:
                        tool_result: Any = await self.tools.execute_tool(
                            tc.name,
                            tc.arguments,
                            bypass_policy=is_superpowered,
                            task_id=task.id,
                            hook_context={
                                "tenant_id": tenant_id,
                                "allowed_tools": allowed_tools,
                                "call_index": call_index,
                            },
                        )
                    except PermissionError as exc:
                        tool_errors.append(f"{tc.name}: {exc}")
                        tool_result = {"ok": False, "error": str(exc)}
                    except Exception as exc:
                        tool_errors.append(f"{tc.name}: {exc}")
                        tool_result = {"ok": False, "error": str(exc)}

                    if isinstance(tool_result, dict):
                        cp = tool_result.get("created_paths")
                        if isinstance(cp, list):
                            created_paths.extend(str(p) for p in cp if str(p).strip())
                        up = tool_result.get("updated_paths")
                        if isinstance(up, list):
                            updated_paths.extend(str(p) for p in up if str(p).strip())
                        persisted_artifacts, artifact_created = self._persist_tool_artifacts(
                            task_id=task.id,
                            tenant_id=tenant_id,
                            workspace_root=workspace_root_path,
                            tool_name=tc.name,
                            tool_args=tc.arguments,
                            tool_result=tool_result,
                        )
                        if persisted_artifacts:
                            artifacts.extend(persisted_artifacts)
                            # Emit an artifact_emit stream event for each new artifact
                            for art in persisted_artifacts:
                                yield {
                                    "type": "artifact_emit",
                                    "artifact_id": art.get("artifact_id", ""),
                                    "title": art.get("title", ""),
                                    "mime_type": art.get("mime_type", ""),
                                    "url": art.get("url", ""),
                                }
                        if artifact_created:
                            created_paths.extend(artifact_created)
                        if tc.name == "patch_file":
                            s = tool_result.get("patch_summary")
                            if s and str(s).strip():
                                patch_summaries.append(str(s).strip())
                            # Capture the applied patch text as the diff for the preview panel
                            raw_patch = str(tc.arguments.get("patch", "")).strip() if isinstance(tc.arguments, dict) else ""
                            if raw_patch:
                                last_diff = raw_patch
                        if tc.name == "apply_wiring":
                            ws = tool_result.get("patch_summaries")
                            if isinstance(ws, list):
                                patch_summaries.extend(str(s).strip() for s in ws if str(s).strip())
                            wiring_prov = tool_result.get("provenance")
                            if isinstance(wiring_prov, list):
                                context_provenance.extend(i for i in wiring_prov if isinstance(i, dict))
                            raw_diff = str(tool_result.get("diff", "") or "").strip()
                            if raw_diff:
                                last_diff = raw_diff
                        if tc.name == "read_context":
                            prov = tool_result.get("provenance")
                            if isinstance(prov, list):
                                context_provenance.extend(i for i in prov if isinstance(i, dict))

                    tool_content = json.dumps(tool_result, default=str)
                    total_tokens += model.estimate_tokens(tool_content)
                    condensed = tool_content[:800]
                    if len(tool_content) > 800:
                        condensed += " ...[truncated]"
                    tool_result_lines.append(f"Tool `{tc.name}` called with {json.dumps(tc.arguments)} returned: {condensed}")

                    # ── PostToolUse hook ─────────────────────────────────────
                    if self.hooks is not None:
                        try:
                            await self.hooks.emit(HookPayload(
                                event="PostToolUse",
                                data={
                                    "task_id": task.id,
                                    "tenant_id": tenant_id,
                                    "tool": tc.name,
                                    "arguments": tc.arguments,
                                    "result": tool_result if isinstance(tool_result, dict) else {"raw": str(tool_result)},
                                    "step": step,
                                },
                            ))
                        except Exception:
                            pass

                    ok_flag = isinstance(tool_result, dict) and tool_result.get("ok", True) is not False
                    # Include diff in tool_result events for patch-capable tools
                    tool_diff = ""
                    if tc.name == "patch_file" and isinstance(tc.arguments, dict):
                        tool_diff = str(tc.arguments.get("patch", "") or "").strip()
                    yield {
                        "type": "tool_result",
                        "step": step,
                        "tool": tc.name,
                        "ok": ok_flag,
                        "summary": condensed[:200],
                        **({
                            "diff": tool_diff,
                        } if tool_diff else {}),
                    }

                messages.append({
                    "role": "user",
                    "content": "Tool outputs are now available.\n" + "\n".join(tool_result_lines),
                })
            else:
                if not final_text:
                    final_text = "[Agent reached max steps without producing a final response]"
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
            return

        # ── Stop hook ─────────────────────────────────────────────────────
        if self.hooks is not None:
            try:
                await self.hooks.emit(HookPayload(
                    event="Stop",
                    data={
                        "task_id": task.id,
                        "success": bool(final_text and not final_text.startswith("[Agent reached")),
                        "response": final_text,
                        "used_tools": used_tools,
                    },
                ))
            except Exception:
                pass

        yield {
            "type": "done",
            "task_id": task.id,
            "success": bool(final_text and not final_text.startswith("[Agent reached")),
            "response": final_text,
            "model": last_model_id,
            "used_tools": used_tools,
            "created_paths": list(dict.fromkeys(created_paths)),
            "updated_paths": list(dict.fromkeys(updated_paths)),
            "patch_summaries": list(dict.fromkeys(patch_summaries)),
            "context_provenance": context_provenance,
            "estimated_total_tokens": total_tokens,
            "artifacts": [
                {
                    "artifact_id": art.get("artifact_id", ""),
                    "title": art.get("title", ""),
                    "mime_type": art.get("mime_type", ""),
                    "url": art.get("url", ""),
                }
                for art in {art.get("artifact_id", ""): art for art in artifacts}.values()
            ],
            **({
                "diff": last_diff,
            } if last_diff else {}),
        }

    def _normalize_calls_for_stream(self, raw_calls: list[Any]) -> list[ToolCall]:
        """Thin wrapper: reuse _normalize_tool_call for each raw call."""
        return [self._normalize_tool_call(raw_tc, "") for raw_tc in raw_calls]

    def _build_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for all policy-allowed tools."""
        result = []
        for tool in self.tools.list_tools():
            allowed, _ = self.tools.preview_policy(tool)
            if not allowed:
                continue
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters or {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            })
        return result

    def _resolve_budget(self, task: Task) -> dict[str, int]:
        default_steps = int(self.config.get("state_machine.default_budget.max_steps", 10))
        default_tokens = int(self.config.get("state_machine.default_budget.max_tokens", 8192))
        default_duration = int(self.config.get("state_machine.default_budget.max_duration_ms", 60000))

        workflow_mode = str(task.input.get("workflow_mode", "")).strip().lower() if task.input else ""
        if workflow_mode == "lightning":
            default_steps = int(self.config.get("orchestrator.lightning_mode.default_budget.max_steps", default_steps))
            default_tokens = int(self.config.get("orchestrator.lightning_mode.default_budget.max_tokens", default_tokens))
            default_duration = int(
                self.config.get("orchestrator.lightning_mode.default_budget.max_duration_ms", default_duration)
            )
        elif workflow_mode == "superpowered":
            default_steps = int(self.config.get("orchestrator.superpowered_mode.default_budget.max_steps", default_steps))
            default_tokens = int(self.config.get("orchestrator.superpowered_mode.default_budget.max_tokens", default_tokens))
            if bool(self.config.get("orchestrator.superpowered_mode.disable_budget_timeout", True)):
                # 0 means unbounded wall-clock budget for superpowered runs.
                default_duration = 0
            else:
                default_duration = int(
                    self.config.get("orchestrator.superpowered_mode.default_budget.max_duration_ms", default_duration)
                )

        req_budget = task.input.get("budget", {}) if task.input else {}
        if not isinstance(req_budget, dict):
            req_budget = {}
        return {
            "max_steps": int(req_budget.get("max_steps", default_steps)),
            "max_tokens": int(req_budget.get("max_tokens", default_tokens)),
            "max_duration_ms": int(req_budget.get("max_duration_ms", default_duration)),
        }
