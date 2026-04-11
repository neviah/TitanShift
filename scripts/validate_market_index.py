from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_ITEM_FIELDS = {
    "skill_id",
    "description",
    "mode",
    "domain",
    "version",
    "tags",
    "required_tools",
    "dependencies",
}


def _fail(message: str) -> int:
    print(f"ERROR: {message}")
    return 1


def _validate_item(item: Any, file_path: Path, index: int) -> str | None:
    if not isinstance(item, dict):
        return f"{file_path}: items[{index}] must be an object"
    missing = REQUIRED_ITEM_FIELDS.difference(set(item.keys()))
    if missing:
        return f"{file_path}: items[{index}] missing required fields: {sorted(missing)}"
    skill_id = item.get("skill_id")
    if not isinstance(skill_id, str) or not skill_id.strip():
        return f"{file_path}: items[{index}].skill_id must be a non-empty string"

    array_fields = ["tags", "required_tools", "dependencies"]
    for field in array_fields:
        value = item.get(field)
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            return f"{file_path}: items[{index}].{field} must be an array of strings"
    return None


def validate_market_index(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"{path}: invalid JSON ({exc})"]

    if not isinstance(data, dict):
        return [f"{path}: root must be an object"]

    for field in ["source", "generated_at", "signing_version", "items"]:
        if field not in data:
            errors.append(f"{path}: missing required field '{field}'")

    signing_version = data.get("signing_version")
    if signing_version not in {"v1", "v2-ed25519"}:
        errors.append(f"{path}: signing_version must be 'v1' or 'v2-ed25519'")

    if signing_version == "v2-ed25519":
        if not isinstance(data.get("signature"), str) or not str(data.get("signature", "")).strip():
            errors.append(f"{path}: v2-ed25519 requires non-empty 'signature'")

    items = data.get("items")
    if not isinstance(items, list):
        errors.append(f"{path}: items must be an array")
        return errors

    seen_skill_ids: set[str] = set()
    for idx, item in enumerate(items):
        item_error = _validate_item(item, path, idx)
        if item_error:
            errors.append(item_error)
            continue
        skill_id = str(item.get("skill_id"))
        if skill_id in seen_skill_ids:
            errors.append(f"{path}: duplicate skill_id '{skill_id}'")
        seen_skill_ids.add(skill_id)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate skills market index JSON files.")
    parser.add_argument(
        "--glob",
        dest="glob_pattern",
        default="market/*.json",
        help="Glob pattern for market index files (default: market/*.json)",
    )
    args = parser.parse_args()

    matched = [Path(p) for p in glob.glob(args.glob_pattern)]
    if not matched:
        print(f"No files matched pattern: {args.glob_pattern} (skipped)")
        return 0

    all_errors: list[str] = []
    for path in matched:
        all_errors.extend(validate_market_index(path))

    if all_errors:
        for err in all_errors:
            print(err)
        return _fail(f"Validation failed for {len(all_errors)} issue(s)")

    print(f"Validated {len(matched)} market index file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
