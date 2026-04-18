from __future__ import annotations

import os
import re
import yaml
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
    when_to_use: str = ""


class SkillRegistry:
    def __init__(self, skill_base_path: str = None) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._handlers: dict[str, SkillHandler] = {}
        self.skill_base_path = skill_base_path
        self._load_skill_md_files()

    def _load_skill_md_files(self) -> None:
        """Load skill definitions from SKILL.md files in skill_base_path."""
        if not self.skill_base_path or not os.path.isdir(self.skill_base_path):
            return

        for skill_dir in os.listdir(self.skill_base_path):
            skill_path = os.path.join(self.skill_base_path, skill_dir)
            if not os.path.isdir(skill_path):
                continue

            skill_md = os.path.join(skill_path, "SKILL.md")
            if os.path.isfile(skill_md):
                self._load_skill_from_file(skill_dir, skill_md)

    def _load_skill_from_file(self, skill_name: str, skill_file: str) -> None:
        """Load skill metadata from a SKILL.md file."""
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse YAML frontmatter if present
            frontmatter: dict[str, Any] = {}
            body = content
            if content.startswith("---"):
                end_idx = content.find("\n---", 3)
                if end_idx != -1:
                    fm_text = content[3:end_idx].strip()
                    try:
                        frontmatter = yaml.safe_load(fm_text) or {}
                    except yaml.YAMLError:
                        frontmatter = {}
                    body = content[end_idx + 4:].lstrip()

            # Parse title from first markdown header (fallback)
            title_match = re.search(r"^#\s+(.+?)(?:\n|$)", body, re.MULTILINE)
            title = title_match.group(1) if title_match else skill_name

            # Extract "When to Use" section (fallback)
            when_match = re.search(
                r"## When to Use\n\n(.+?)(?=\n##|\Z)", body, re.DOTALL
            )
            when_to_use = (
                when_match.group(1).strip()[:300]
                if when_match
                else "Use this skill as needed."
            )

            # First paragraph as description (fallback)
            desc_match = re.search(
                r"^[^#](.+?)(?:\n\n|$)", body.split("## When to Use")[0], re.DOTALL
            )
            description_fallback = (
                desc_match.group(1).strip()[:150]
                if desc_match
                else f"Skill: {title}"
            )

            # Frontmatter fields override parsed values
            description = str(frontmatter.get("description", description_fallback))[:300]
            domain = str(frontmatter.get("domain", "workflow"))
            version = str(frontmatter.get("version", "1.0.0"))
            mode = str(frontmatter.get("mode", "prompt"))
            raw_tags = frontmatter.get("tags", ["superpowered", "builtin"])
            tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else ["superpowered", "builtin"]

            skill = SkillDefinition(
                skill_id=skill_name,
                description=description,
                when_to_use=when_to_use,
                mode=mode,
                domain=domain,
                tags=tags,
                version=version,
            )
            self._skills[skill_name] = skill
        except Exception as e:
            print(f"Warning: Failed to load skill {skill_name}: {e}")

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

    def format_for_system_prompt(self, workflow_mode: str = "lightning") -> str:
        """Format skill list for injection into system prompt.

        Returns compact markdown listing for discovery.
        """
        # Filter skills based on mode
        if workflow_mode == "superpowered":
            # Show all skills, especially those tagged as superpowered
            skills_to_show = [s for s in self.list_skills() if "builtin" in s.tags or "superpowered" in s.tags]
        else:
            # Lightning mode: avoid injecting built-in workflow skills that models may mistake for tools.
            skills_to_show = [s for s in self.list_skills() if "builtin" not in s.tags and "superpowered" not in s.tags]

        if not skills_to_show:
            return ""

        lines = [
            "## Available Skills\n",
            "These are workflow patterns and prompts, not callable tools.",
            "Do not emit skill names inside <tool_call> blocks.",
            "Only call actual tools from the provided tool schema; use these skills implicitly as guidance.\n",
        ]
        for skill in sorted(skills_to_show, key=lambda s: s.skill_id):
            # Skip the built-in reactive_chat and safe_shell_command for prompt display
            if skill.skill_id in ("reactive_chat", "safe_shell_command"):
                continue
            lines.append(f"- **{skill.skill_id}** — {skill.description}")

        return "\n".join(lines)

    def get_superpowered_initial_chain(self) -> list[str]:
        """Get the mandatory skill chain for Superpowered mode.

        Returns: ["brainstorming", "writing-plans", "subagent-driven-development"]
        """
        required = ["brainstorming", "writing-plans", "subagent-driven-development"]
        # Filter to only skills that actually exist
        return [s for s in required if s in self._skills]
