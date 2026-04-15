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
                    tool_content = json.dumps(result)
                except PermissionError as exc:
                    tool_errors.append(f"{tc.name}: {exc}")
                    if tc.name == "shell_command":
                        fallback_args = {
                            "url": f"https://duckduckgo.com/html/?q={quote_plus(task.description)}"
                        }
                        try:
                            fallback = await self.tools.execute_tool("web_fetch", fallback_args)
                            tool_content = json.dumps(
                                {
                                    "ok": True,
                                    "fallback": "web_fetch",
                                    "original_error": str(exc),
                                    "result": fallback,
                                }
                            )
                        except Exception as fallback_exc:
                            tool_content = json.dumps(
                                {
                                    "ok": False,
                                    "error": str(exc),
                                    "fallback_error": str(fallback_exc),
                                }
                            )
                    else:
                        tool_content = json.dumps({"ok": False, "error": str(exc)})
                except Exception as exc:
                    tool_errors.append(f"{tc.name}: {exc}")
                    tool_content = json.dumps({"ok": False, "error": str(exc)})

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
        fallback_used = bool(requested_set) and bool(used_tools) and not bool(used_requested)
        primary_failure_reason = None
        if tool_errors:
            primary_failure_reason = tool_errors[0]
        elif requested_set and not used_requested:
            primary_failure_reason = "Requested tools were not used by model output"

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
            },
            success=bool(final_text and not final_text.startswith("[Agent reached")),
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
