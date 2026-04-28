"""Validate SKILL.md files against the Agent Skills specification.

Spec reference: https://agentskills.io/specification

Required frontmatter fields:
  name        - 1-64 chars, lowercase alphanumeric + hyphens, no leading/trailing/
                consecutive hyphens, must match parent directory name
  description - 1-1024 chars, non-empty

Optional frontmatter fields (validated if present):
  license         - non-empty string
  compatibility   - 1-500 chars
  metadata        - dict of string keys and values
  allowed-tools   - space-separated string of tool names

Non-spec TitanShift extension fields (allowed, not validated for format):
  version, domain, mode, tags, source, required_tools, dependencies
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)

_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_CONSEC_HYPHEN_RE = re.compile(r"--")

SKILLS_ROOT = Path(__file__).parent.parent / "harness" / "skills"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body) from a SKILL.md file."""
    if not content.startswith("---"):
        return {}, content
    end_idx = content.find("\n---", 3)
    if end_idx == -1:
        return {}, content
    fm_text = content[3:end_idx].strip()
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error: {exc}") from exc
    body = content[end_idx + 4:].lstrip()
    return fm if isinstance(fm, dict) else {}, body


def validate_skill(skill_dir: Path) -> list[str]:
    """Validate a single skill directory. Returns list of error messages."""
    errors: list[str] = []
    skill_name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        errors.append("SKILL.md not found")
        return errors

    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"Cannot read SKILL.md: {exc}")
        return errors

    try:
        fm, _body = _parse_frontmatter(content)
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    # --- name field ---
    name = fm.get("name")
    if not name:
        errors.append("Missing required field: name")
    else:
        name = str(name)
        if len(name) > 64:
            errors.append(f"name too long ({len(name)} chars, max 64)")
        if name != name.lower():
            errors.append("name must be lowercase")
        if not _NAME_RE.match(name):
            errors.append(
                "name must contain only lowercase letters, numbers, and hyphens; "
                "must not start or end with a hyphen"
            )
        if _CONSEC_HYPHEN_RE.search(name):
            errors.append("name must not contain consecutive hyphens (--)")
        if name != skill_name:
            errors.append(
                f"name '{name}' does not match directory name '{skill_name}'"
            )

    # --- description field ---
    description = fm.get("description")
    if not description:
        errors.append("Missing required field: description")
    else:
        desc_str = str(description)
        if len(desc_str) > 1024:
            errors.append(f"description too long ({len(desc_str)} chars, max 1024)")
        if not desc_str.strip():
            errors.append("description must not be blank")

    # --- license field (optional) ---
    if "license" in fm:
        lic = fm["license"]
        if not str(lic).strip():
            errors.append("license field is present but empty")

    # --- compatibility field (optional) ---
    if "compatibility" in fm:
        compat = str(fm["compatibility"])
        if len(compat) > 500:
            errors.append(
                f"compatibility too long ({len(compat)} chars, max 500)"
            )
        if not compat.strip():
            errors.append("compatibility field is present but empty")

    # --- metadata field (optional) ---
    if "metadata" in fm:
        meta = fm["metadata"]
        if not isinstance(meta, dict):
            errors.append("metadata must be a key-value mapping (dict)")
        else:
            for k, v in meta.items():
                if not isinstance(k, str):
                    errors.append(f"metadata key '{k}' must be a string")

    # --- allowed-tools field (optional) ---
    if "allowed-tools" in fm:
        at = fm["allowed-tools"]
        if not isinstance(at, str) or not at.strip():
            errors.append(
                "allowed-tools must be a non-empty space-separated string of tool names"
            )

    return errors


def main() -> int:
    skills_root = SKILLS_ROOT
    if not skills_root.is_dir():
        print(f"ERROR: Skills directory not found: {skills_root}", file=sys.stderr)
        return 1

    skill_dirs = sorted(
        p for p in skills_root.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )

    if not skill_dirs:
        print("No skill directories found.", file=sys.stderr)
        return 1

    total = 0
    failed = 0
    for skill_dir in skill_dirs:
        total += 1
        errors = validate_skill(skill_dir)
        if errors:
            failed += 1
            print(f"FAIL  {skill_dir.name}")
            for err in errors:
                print(f"      - {err}")
        else:
            print(f"PASS  {skill_dir.name}")

    print()
    if failed:
        print(f"{failed}/{total} skill(s) failed validation.")
        return 1
    else:
        print(f"All {total} skill(s) passed validation.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
