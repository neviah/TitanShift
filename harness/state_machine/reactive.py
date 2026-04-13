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

    def _normalize_tool_call(self, tool_call: ToolCall) -> ToolCall:
        name = tool_call.name.strip()
        args = dict(tool_call.arguments)

        aliases: dict[str, str] = {
            "web_search_basic": "web_fetch",
            "web_search": "web_fetch",
            "search_web": "web_fetch",
            "browser_search": "web_fetch",
            "web.browse": "web_fetch",
        }
        normalized = aliases.get(name, name)

        if normalized == "web_fetch":
            if "url" not in args:
                query = str(args.get("query") or args.get("q") or "").strip()
                if query:
                    args["url"] = f"https://duckduckgo.com/html/?q={quote_plus(query)}"

            url = str(args.get("url", "")).strip()
            if url and not url.startswith(("http://", "https://")):
                args["url"] = f"https://{url.lstrip('/')}"

        return ToolCall(id=tool_call.id, name=normalized, arguments=args)

    async def run_task(self, task: Task) -> TaskResult:
        budget = self._resolve_budget(task)
        if budget["max_steps"] < 1:
            return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: max_steps < 1")

        preferred_backend = task.input.get("model_backend") if task.input else None
        workspace_root = task.input.get("workspace_root") if task.input else None
        model = self.models.select_model(preferred_backend)

        # System prompt
        system_parts = [
            "You are a helpful AI assistant integrated into the TitanShift agent harness.",
            "When you need to look up live information, fetch web pages, check news, prices, search results, "
            "or any real-time data — always use the web_fetch tool. Do not explain that you cannot browse; "
            "just call the tool with the appropriate URL.",
        ]
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
        tool_defs = self._build_tool_definitions()

        # Multi-turn message history
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task.description},
        ]

        used_tools: list[str] = []
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
                tc = self._normalize_tool_call(raw_tc)
                used_tools.append(tc.name)
                try:
                    result = await self.tools.execute_tool(tc.name, tc.arguments)
                    tool_content = json.dumps(result)
                except Exception as exc:
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

        return TaskResult(
            task_id=task.id,
            output={
                "response": final_text,
                "model": last_model_id,
                "mode": "reactive",
                "estimated_total_tokens": total_tokens,
                "used_tools": used_tools,
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

        req_budget = task.input.get("budget", {}) if task.input else {}
        return {
            "max_steps": int(req_budget.get("max_steps", default_steps)),
            "max_tokens": int(req_budget.get("max_tokens", default_tokens)),
            "max_duration_ms": int(req_budget.get("max_duration_ms", default_duration)),
        }
