from __future__ import annotations

import asyncio
import json
from typing import Any

from harness.model.adapter import ModelRegistry, ModelRequest, ToolCall
from harness.runtime.config import ConfigManager
from harness.runtime.types import Task, TaskResult
from harness.tools.registry import ToolRegistry


class ReactiveStateMachine:
    """Agentic tool-calling loop: LLM decides which tools to use, the loop executes them
    and feeds results back until the model returns a final text response."""

    def __init__(self, models: ModelRegistry, config: ConfigManager, tools: ToolRegistry) -> None:
        self.models = models
        self.config = config
        self.tools = tools

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
        system_prompt = " ".join(system_parts)

        # Build OpenAI-format tool definitions from the registry
        tool_defs = self._build_tool_definitions()

        # Multi-turn message history
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task.description},
        ]

        used_tools: list[str] = []
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
                response = await asyncio.wait_for(
                    model.generate(ModelRequest(
                        prompt="",
                        system_prompt=system_prompt,
                        messages=messages,
                        tool_definitions=tool_defs or None,
                    )),
                    timeout=budget["max_duration_ms"] / 1000.0,
                )
            except asyncio.TimeoutError:
                return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: task timeout")

            last_model_id = response.model_id

            if not response.tool_calls:
                # LLM produced a final text answer — done
                final_text = response.text
                total_tokens += model.estimate_tokens(response.text)
                break

            # --- Execute tool calls and append results to history ---
            # Append the assistant message that requested the tools
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            })

            for tc in response.tool_calls:
                used_tools.append(tc.name)
                try:
                    result = await self.tools.execute_tool(tc.name, tc.arguments)
                    tool_content = json.dumps(result)
                except Exception as exc:
                    tool_content = json.dumps({"ok": False, "error": str(exc)})

                total_tokens += model.estimate_tokens(tool_content)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": tool_content,
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
