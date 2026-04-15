from __future__ import annotations

import asyncio
import json
from urllib.parse import quote_plus
from typing import Any

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
    ) -> None:
        self.models = models
        self.config = config
        self.tools = tools
        self.skills = skills

    def _normalize_tool_call(self, tool_call: ToolCall, task_description: str) -> ToolCall:
        name = tool_call.name.strip()
        args = dict(tool_call.arguments)

        aliases: dict[str, str] = {
            "web_search_basic": "web_fetch",
            "web_search": "web_fetch",
            "search_web": "web_fetch",
            "browser_search": "web_fetch",
            "web.browse": "web_fetch",
            "file_write": "write_file",
            "write_workspace_file": "write_file",
            "save_file": "write_file",
            "mkdir": "create_directory",
            "create_folder": "create_directory",
        }
        normalized = aliases.get(name, name)

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

        if normalized == "shell_command" and web_intent:
            command = str(args.get("command", "")).strip()
            query = command or task_description
            return ToolCall(
                id=tool_call.id,
                name="web_fetch",
                arguments={"url": f"https://duckduckgo.com/html/?q={quote_plus(query)}"},
            )

        return ToolCall(id=tool_call.id, name=normalized, arguments=args)

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

        # Intent aliases for repo-intake generated camofox tools
        if "camofox" in text:
            for tool_name in available:
                lower_name = tool_name.lower()
                if "camofox" in lower_name and lower_name.startswith("repo_"):
                    matched.add(tool_name)

        return sorted(matched)

    def _build_active_tool_definitions(self, requested_tools: list[str]) -> list[dict[str, Any]]:
        """Build tool definitions, optionally narrowed when user explicitly requests tools."""
        all_defs = self._build_tool_definitions()
        if not requested_tools:
            return all_defs

        support_tools = {
            "create_directory",
            "write_file",
            "append_file",
            "read_file",
            "list_directory",
            "rename_or_move",
            "delete_file",
            "search_workspace",
        }
        requested = set(requested_tools)
        filtered = [
            td
            for td in all_defs
            if str(td.get("function", {}).get("name", "")) in requested
            or str(td.get("function", {}).get("name", "")) in support_tools
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

        is_browser_tool = lower_name == "web_fetch" or "camofox" in lower_name
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

    async def run_task(self, task: Task) -> TaskResult:
        budget = self._resolve_budget(task)
        if budget["max_steps"] < 1:
            return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: max_steps < 1")

        preferred_backend = task.input.get("model_backend") if task.input else None
        workspace_root = task.input.get("workspace_root") if task.input else None
        model = self.models.select_model(preferred_backend)

        # System prompt
        requested_tools = self._detect_requested_tools(task.description)
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
        if workspace_root:
            system_parts.append(
                f"The active workspace folder is: {workspace_root}. "
                "When creating or modifying files, use paths relative to this workspace."
            )

        # Inject available skills if skill registry is available
        if self.skills:
            workflow_mode = task.input.get("workflow_mode") if task.input else self.config.get("orchestrator.workflow_mode", "lightning")
            skills_section = self.skills.format_for_system_prompt(workflow_mode)
            if skills_section:
                system_parts.append("\n" + skills_section)

        system_prompt = " ".join(system_parts)

        # Build OpenAI-format tool definitions from the registry
        tool_defs = self._build_active_tool_definitions(requested_tools)

        # Multi-turn message history
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task.description},
        ]

        used_tools: list[str] = []
        tool_errors: list[str] = []
        last_tool_result_lines: list[str] = []
        browser_proofs: list[dict[str, Any]] = []
        test_failure_summary: list[str] = []
        test_failed_count: int | None = None
        created_paths: list[str] = []
        updated_paths: list[str] = []
        generated_app_service: dict[str, Any] | None = None
        final_text = ""
        last_model_id = model.model_id
        total_tokens = model.estimate_tokens(task.description)
        response = None

        for step in range(budget["max_steps"]):
            if total_tokens > budget["max_tokens"]:
                return TaskResult(
                    task_id=task.id,
                    output={"response": final_text, "mode": "reactive", "used_tools": used_tools},
                    success=False,
                    error="Budget exceeded: token limit reached",
                )

            try:
                active_tool_defs = tool_defs if not used_tools else None
                response = await asyncio.wait_for(
                    model.generate(ModelRequest(
                        prompt="",
                        system_prompt=system_prompt,
                        messages=messages,
                        tool_definitions=active_tool_defs,
                        timeout_s=max(5.0, min(float(getattr(model, "timeout_s", 45.0)), budget["max_duration_ms"] / 1000.0)),
                    )),
                    timeout=budget["max_duration_ms"] / 1000.0,
                )
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
                # LLM produced a final text answer — done
                final_text = response.text
                total_tokens += model.estimate_tokens(response.text)
                break

            # --- Execute tool calls and append results to history ---
            # LM Studio compatibility note: some model/server combos reject tool-role messages.
            # We therefore feed tool outputs back as plain user context for the next turn.
            tool_result_lines: list[str] = []
            for raw_tc in response.tool_calls:
                tc = self._normalize_tool_call(raw_tc, task.description)
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
                try:
                    result = await self.tools.execute_tool(tc.name, tc.arguments)
                    tool_result: dict[str, Any] | Any = result
                except PermissionError as exc:
                    tool_errors.append(f"{tc.name}: {exc}")
                    if tc.name == "shell_command":
                        fallback_args = {
                            "url": f"https://duckduckgo.com/html/?q={quote_plus(task.description)}"
                        }
                        try:
                            fallback = await self.tools.execute_tool("web_fetch", fallback_args)
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
                    service_manifest = tool_result.get("app_service_manifest")
                    if isinstance(service_manifest, dict):
                        generated_app_service = service_manifest

                if tc.name == "run_tests" and isinstance(tool_result, dict):
                    failure_rows = tool_result.get("failure_summary")
                    if isinstance(failure_rows, list):
                        test_failure_summary.extend(str(row).strip() for row in failure_rows if str(row).strip())
                    failed_count = tool_result.get("failed_count")
                    if isinstance(failed_count, int):
                        test_failed_count = max(test_failed_count or 0, failed_count)

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

        requested_set = set(requested_tools)
        used_requested = [name for name in used_tools if name in requested_set]
        missing_requested_tools = bool(requested_set) and not bool(used_requested)
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
                "generated_app_service": generated_app_service,
            },
            success=bool(final_text and not final_text.startswith("[Agent reached") and not missing_requested_tools),
        )

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

        req_budget = task.input.get("budget", {}) if task.input else {}
        return {
            "max_steps": int(req_budget.get("max_steps", default_steps)),
            "max_tokens": int(req_budget.get("max_tokens", default_tokens)),
            "max_duration_ms": int(req_budget.get("max_duration_ms", default_duration)),
        }
