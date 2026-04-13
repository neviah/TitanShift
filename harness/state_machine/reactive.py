from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus

from harness.model.adapter import ModelRegistry, ModelRequest
from harness.runtime.config import ConfigManager
from harness.runtime.types import Task, TaskResult
from harness.tools.registry import ToolRegistry


class ReactiveStateMachine:
    """Phase 1 reactive loop: single pass plan-act-reflect shape."""

    def __init__(self, models: ModelRegistry, config: ConfigManager, tools: ToolRegistry) -> None:
        self.models = models
        self.config = config
        self.tools = tools

    async def run_task(self, task: Task) -> TaskResult:
        budget = self._resolve_budget(task)
        if budget["max_steps"] < 1:
            return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: max_steps < 1")

        preferred_backend = task.input.get("model_backend") if task.input else None
        available_tools = task.input.get("available_tools", []) if task.input else []
        workspace_root = task.input.get("workspace_root") if task.input else None
        model = self.models.select_model(preferred_backend)

        # Build system prompt with workspace context
        system_parts = ["You are a helpful AI assistant integrated into the TitanShift agent harness."]
        if workspace_root:
            system_parts.append(
                f"The active workspace folder is: {workspace_root}. "
                "When creating or modifying files, always use paths relative to or within this workspace folder. "
                "Do not create or modify files outside this workspace."
            )
        if available_tools:
            tool_names = ", ".join(t.get("name", "") for t in available_tools)
            system_parts.append(f"You have access to the following tools: {tool_names}.")
            system_parts.append(
                "For requests requiring live web data (news, weather, current events, websites), "
                "use the available web tools and ground your answer in tool output."
            )
        system_prompt = " ".join(system_parts)

        tool_context, used_tools = await self._collect_tool_context(task.description, available_tools)
        model_prompt = task.description
        if tool_context:
            model_prompt = (
                f"{task.description}\n\n"
                "Tool output (trusted context):\n"
                f"{tool_context}\n\n"
                "Use the tool output above as primary evidence. If data is missing, state limitations clearly."
            )

        prompt_tokens = model.estimate_tokens(task.description)
        if prompt_tokens > budget["max_tokens"]:
            return TaskResult(
                task_id=task.id,
                output={"prompt_tokens": prompt_tokens},
                success=False,
                error="Budget exceeded: prompt token estimate is above max_tokens",
            )

        try:
            response = await asyncio.wait_for(
                model.generate(ModelRequest(
                    prompt=model_prompt,
                    system_prompt=system_prompt,
                    available_tools=available_tools or None
                )),
                timeout=budget["max_duration_ms"] / 1000.0,
            )
        except TimeoutError:
            return TaskResult(task_id=task.id, output={}, success=False, error="Budget exceeded: task timeout")

        total_tokens = prompt_tokens + model.estimate_tokens(response.text)
        if total_tokens > budget["max_tokens"]:
            return TaskResult(
                task_id=task.id,
                output={
                    "response": response.text,
                    "model": response.model_id,
                    "mode": "reactive",
                    "estimated_total_tokens": total_tokens,
                    "used_tools": used_tools,
                },
                success=False,
                error="Budget exceeded: estimated total tokens above max_tokens",
            )

        return TaskResult(
            task_id=task.id,
            output={
                "response": response.text,
                "model": response.model_id,
                "mode": "reactive",
                "estimated_total_tokens": total_tokens,
                "used_tools": used_tools,
            },
            success=True,
        )

    async def _collect_tool_context(
        self,
        prompt: str,
        available_tools: list[dict[str, str]],
    ) -> tuple[str, list[str]]:
        allowed = {str(t.get("name", "")).strip() for t in available_tools}
        if "web_fetch" not in allowed:
            return "", []

        lower = prompt.lower()
        looks_web = any(k in lower for k in ["http://", "https://", "www.", "website", "news", "weather", "headline", "story"])
        if not looks_web:
            return "", []

        url = self._extract_url(prompt)
        if not url:
            weather_match = re.search(r"weather\s+(?:in|for)\s+([a-zA-Z\s,]+)", prompt, flags=re.IGNORECASE)
            if weather_match:
                location = weather_match.group(1).strip().strip("?.!")
                url = f"https://wttr.in/{quote_plus(location)}?format=3"
            elif "msnbc" in lower:
                url = "https://www.msnbc.com/"

        if not url:
            return "", []

        try:
            result = await self.tools.execute_tool("web_fetch", {"url": url, "timeout_s": 12, "max_chars": 5000})
        except Exception as exc:
            return f"web_fetch failed for {url}: {exc}", ["web_fetch"]

        content = str(result.get("content", "")).strip()
        if not content:
            return f"web_fetch returned no content for {url}", ["web_fetch"]

        return f"Source URL: {result.get('url', url)}\n{content}", ["web_fetch"]

    @staticmethod
    def _extract_url(text: str) -> str | None:
        m = re.search(r"https?://[^\s)\]>\"']+", text)
        return m.group(0) if m else None

    def _resolve_budget(self, task: Task) -> dict[str, int]:
        default_steps = int(self.config.get("state_machine.default_budget.max_steps", 1))
        default_tokens = int(self.config.get("state_machine.default_budget.max_tokens", 8192))
        default_duration = int(self.config.get("state_machine.default_budget.max_duration_ms", 60000))

        req_budget = task.input.get("budget", {}) if task.input else {}
        return {
            "max_steps": int(req_budget.get("max_steps", default_steps)),
            "max_tokens": int(req_budget.get("max_tokens", default_tokens)),
            "max_duration_ms": int(req_budget.get("max_duration_ms", default_duration)),
        }
