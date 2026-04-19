from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PATH_KEYS = {"created_paths", "updated_paths"}


@dataclass
class ValidationIssue:
    telemetry_file: Path
    path_value: str
    reason: str


def _to_abs_path(raw_path: str, workspace_root: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (workspace_root / candidate).resolve()


def _collect_path_values(node: Any) -> list[str]:
    values: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in PATH_KEYS and isinstance(nested, list):
                    for item in nested:
                        if isinstance(item, str) and item.strip():
                            values.append(item.strip())
                else:
                    walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return values


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_testing_outputs(
    workspace_root: Path,
    testing_root: Path,
    strict_report: bool,
    require_existing_paths: bool,
) -> tuple[list[ValidationIssue], int, int]:
    telemetry_files = sorted(testing_root.rglob("telemetry.json"))
    issues: list[ValidationIssue] = []
    checked_paths = 0

    if not telemetry_files:
        return issues, 0, 0

    for telemetry_file in telemetry_files:
        run_dir = telemetry_file.parent
        if strict_report and not (run_dir / "report.json").exists():
            issues.append(
                ValidationIssue(
                    telemetry_file=telemetry_file,
                    path_value="report.json",
                    reason="missing report.json in run folder",
                )
            )

        try:
            payload = _load_json(telemetry_file)
        except Exception as exc:  # pragma: no cover - defensive branch
            issues.append(
                ValidationIssue(
                    telemetry_file=telemetry_file,
                    path_value="<telemetry.json>",
                    reason=f"invalid JSON: {exc}",
                )
            )
            continue

        for raw_path in _collect_path_values(payload):
            checked_paths += 1
            abs_path = _to_abs_path(raw_path, workspace_root)
            if testing_root not in abs_path.parents and abs_path != testing_root:
                issues.append(
                    ValidationIssue(
                        telemetry_file=telemetry_file,
                        path_value=raw_path,
                        reason=f"path resolves outside Testing root ({abs_path})",
                    )
                )
                continue

            if require_existing_paths and not abs_path.exists():
                issues.append(
                    ValidationIssue(
                        telemetry_file=telemetry_file,
                        path_value=raw_path,
                        reason=f"path does not exist on disk ({abs_path})",
                    )
                )

    return issues, len(telemetry_files), checked_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that all created/updated artifact paths recorded in Testing telemetry "
            "remain under the Testing root."
        )
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root used to resolve relative telemetry paths (default: current directory)",
    )
    parser.add_argument(
        "--testing-root",
        default="Testing",
        help="Testing root folder containing suite run directories (default: Testing)",
    )
    parser.add_argument(
        "--strict-report",
        action="store_true",
        help="Require a report.json next to each telemetry.json",
    )
    parser.add_argument(
        "--require-existing-paths",
        action="store_true",
        help="Fail if any created/updated path in telemetry does not exist on disk",
    )

    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    testing_root = Path(args.testing_root)
    if not testing_root.is_absolute():
        testing_root = (workspace_root / testing_root).resolve()
    else:
        testing_root = testing_root.resolve()

    if not testing_root.exists():
        print(f"Testing root not found: {testing_root}")
        return 0

    issues, telemetry_count, checked_paths = validate_testing_outputs(
        workspace_root=workspace_root,
        testing_root=testing_root,
        strict_report=bool(args.strict_report),
        require_existing_paths=bool(args.require_existing_paths),
    )

    if telemetry_count == 0:
        print(f"No telemetry.json files found under: {testing_root}")
        return 0

    if issues:
        print(
            f"Validation failed: {len(issues)} issue(s) across "
            f"{telemetry_count} telemetry file(s), {checked_paths} path entries checked."
        )
        for issue in issues:
            rel = issue.telemetry_file.relative_to(workspace_root)
            print(f"- {rel}: {issue.path_value} -> {issue.reason}")
        return 1

    print(
        f"Validation passed: {telemetry_count} telemetry file(s), "
        f"{checked_paths} path entries checked, all within {testing_root}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
