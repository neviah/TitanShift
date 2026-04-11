from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from typing import Awaitable, Callable


SkillHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass(slots=True)
class SkillDefinition:
    skill_id: str
    description: str
    mode: str = "prompt"
    domain: str = "general"
    author: str = "local"
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    prompt_template: str | None = None


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._handlers: dict[str, SkillHandler] = {}

    def register_skill(self, skill: SkillDefinition) -> None:
        self._skills[skill.skill_id] = skill

    def unregister_skill(self, skill_id: str) -> bool:
        removed = self._skills.pop(skill_id, None) is not None
        self._handlers.pop(skill_id, None)
        return removed

    def register_code_handler(self, skill_id: str, handler: SkillHandler) -> None:
        self._handlers[skill_id] = handler

    def get_skill(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def list_skills(self) -> list[SkillDefinition]:
        return [self._skills[k] for k in sorted(self._skills.keys())]

    def search_skills(self, query: str, tags: list[str] | None = None) -> list[SkillDefinition]:
        q = query.lower().strip()
        required_tags = [t.lower().strip() for t in (tags or []) if t.strip()]

        def _matches(skill: SkillDefinition) -> bool:
            text_match = (
                not q
                or q in skill.skill_id.lower()
                or q in skill.description.lower()
                or any(q in tag.lower() for tag in skill.tags)
                or q in skill.domain.lower()
            )
            if not text_match:
                return False
            if not required_tags:
                return True
            skill_tags = {t.lower() for t in skill.tags}
            return all(tag in skill_tags for tag in required_tags)

        return [
            s
            for s in self._skills.values()
            if _matches(s)
        ]

    async def execute_skill(self, skill_id: str, _input: dict[str, Any]) -> dict[str, Any]:
        skill = self._skills.get(skill_id)
        if skill is None:
            raise KeyError(f"Skill not found: {skill_id}")

        if skill.mode == "code":
            handler = self._handlers.get(skill_id)
            if handler is None:
                return {
                    "ok": False,
                    "skill_id": skill_id,
                    "mode": "code",
                    "error": "No code handler registered",
                }
            result = handler(_input)
            if hasattr(result, "__await__"):
                result = await result  # type: ignore[assignment]
            if isinstance(result, dict):
                return {"ok": True, "skill_id": skill_id, "mode": "code", "result": result}
            return {"ok": True, "skill_id": skill_id, "mode": "code", "result": {"value": result}}

        template = skill.prompt_template or "Skill {skill_id} received: {input}"
        rendered = template.format(skill_id=skill.skill_id, input=_input)
        return {
            "ok": True,
            "skill_id": skill_id,
            "mode": "prompt",
            "rendered_prompt": rendered,
            "phase": 2,
        }
