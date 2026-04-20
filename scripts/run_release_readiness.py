from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _run_json_command(command: list[str], cwd: Path) -> tuple[int, dict[str, Any] | None, str, str]:
    proc = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    payload: dict[str, Any] | None = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
    return proc.returncode, payload, stdout, stderr


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run release-readiness pipeline: preflight + matrix + output validator, "
            "and emit one summary JSON."
        )
    )
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Harness API base URL")
    parser.add_argument("--testing-root", default="Testing", help="Testing output root")
    parser.add_argument(
        "--suites",
        default="P0_core_reliability,P1_frontend_quality,P2_web_file_integrity,P3_skill_activation,P4_creator_use_cases,P5_regression_gate",
        help="Comma-separated suites passed to matrix runner",
    )
    parser.add_argument(
        "--summary-path",
        default="Testing/release_readiness_summary.json",
        help="Where to write aggregate summary JSON",
    )

    args = parser.parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    testing_root = Path(args.testing_root)
    if not testing_root.is_absolute():
        testing_root = (workspace_root / testing_root).resolve()
    else:
        testing_root = testing_root.resolve()

    summary_path = Path(args.summary_path)
    if not summary_path.is_absolute():
        summary_path = (workspace_root / summary_path).resolve()
    else:
        summary_path = summary_path.resolve()

    python_bin = sys.executable

    started_at = datetime.now(timezone.utc)

    preflight_cmd = [
        python_bin,
        str((workspace_root / "scripts" / "testing_preflight.py").resolve()),
        "--workspace-root",
        str(workspace_root),
        "--remotion-project",
        "frontend",
        "--testing-root",
        str(testing_root),
        "--json",
    ]

    matrix_cmd = [
        python_bin,
        str((workspace_root / "scripts" / "run_harness_matrix.py").resolve()),
        "--base-url",
        args.base_url,
        "--workspace-root",
        str(workspace_root),
        "--output-root",
        str(testing_root),
        "--suites",
        args.suites,
    ]

    validate_cmd = [
        python_bin,
        str((workspace_root / "scripts" / "validate_testing_outputs.py").resolve()),
        "--workspace-root",
        str(workspace_root),
        "--testing-root",
        str(testing_root),
        "--strict-report",
        "--require-existing-paths",
        "--json",
    ]

    preflight_rc, preflight_payload, preflight_stdout, preflight_stderr = _run_json_command(preflight_cmd, workspace_root)
    matrix_rc, matrix_payload, matrix_stdout, matrix_stderr = _run_json_command(matrix_cmd, workspace_root)
    validate_rc, validate_payload, validate_stdout, validate_stderr = _run_json_command(validate_cmd, workspace_root)

    completed_at = datetime.now(timezone.utc)

    summary = {
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 2),
        "workspace_root": str(workspace_root).replace("\\", "/"),
        "testing_root": str(testing_root).replace("\\", "/"),
        "base_url": args.base_url,
        "commands": {
            "preflight": preflight_cmd,
            "matrix": matrix_cmd,
            "validate": validate_cmd,
        },
        "steps": {
            "preflight": {
                "exit_code": preflight_rc,
                "ok": preflight_rc == 0,
                "payload": preflight_payload,
                "stdout": preflight_stdout,
                "stderr": preflight_stderr,
            },
            "matrix": {
                "exit_code": matrix_rc,
                "ok": matrix_rc == 0,
                "payload": matrix_payload,
                "stdout": matrix_stdout,
                "stderr": matrix_stderr,
            },
            "validate": {
                "exit_code": validate_rc,
                "ok": validate_rc == 0,
                "payload": validate_payload,
                "stdout": validate_stdout,
                "stderr": validate_stderr,
            },
        },
    }

    overall_ok = all(summary["steps"][name]["ok"] for name in ("preflight", "matrix", "validate"))
    summary["ok"] = overall_ok

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
