from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SkillDefinition:
    skill_id: str
    description: str
    tags: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register_skill(self, skill: SkillDefinition) -> None:
        self._skills[skill.skill_id] = skill

    def search_skills(self, query: str) -> list[SkillDefinition]:
        q = query.lower()
        return [
            s
            for s in self._skills.values()
            if q in s.description.lower() or any(q in tag.lower() for tag in s.tags)
        ]

    async def execute_skill(self, skill_id: str, _input: dict[str, Any]) -> dict[str, Any]:
        if skill_id not in self._skills:
            raise KeyError(f"Skill not found: {skill_id}")
        return {"ok": True, "skill_id": skill_id, "phase": 1}
