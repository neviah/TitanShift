from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.runtime.bootstrap import build_runtime


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


async def _execute_smoke(workspace_root: Path, output_root: Path) -> dict[str, Any]:
    runtime = build_runtime(workspace_root)

    telemetry: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "workspace_root": str(workspace_root).replace("\\", "/"),
        "steps": [],
    }

    run_id = f"pdf-smoke-{_now_stamp()}"
    run_dir = output_root / run_id
    artifact_dir = run_dir / "pdf"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    report_result: dict[str, Any] = {}
    try:
        report_result = await runtime.tools.execute_tool(
            "generate_report",
            {
                "title": "Office and PDF Smoke",
                "format": "pdf",
                "target_path": str(artifact_dir),
                "sections": [
                    {"heading": "Summary", "body": "PDF smoke generation from TitanShift."},
                ],
                "overwrite": True,
            },
        )
        telemetry["steps"].append({"tool": "generate_report", "ok": True, "result": report_result})
    except Exception as exc:
        telemetry["steps"].append({"tool": "generate_report", "ok": False, "error": str(exc)})

    telemetry["completed_at"] = datetime.now(timezone.utc).isoformat()

    pdf_ok = bool(report_result.get("ok")) and bool(report_result.get("artifacts"))
    summary = {
        "run_id": run_id,
        "suite": "P4_creator_use_cases",
        "scenario": "pdf_smoke",
        "run_dir": str(run_dir).replace("\\", "/"),
        "pdf_ok": pdf_ok,
        "status": "passed" if pdf_ok else "failed",
        "notes": ["OfficeCLI integration removed; PDF generation is the deterministic document gate."],
    }

    _write_json(run_dir / "telemetry.json", telemetry)
    _write_json(run_dir / "report.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PDF smoke workflow and write evidence under Testing/.")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    parser.add_argument(
        "--output-root",
        default="Testing/P4_creator_use_cases",
        help="Output root for smoke run evidence",
    )
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = (workspace_root / output_root).resolve()

    summary = asyncio.run(_execute_smoke(workspace_root=workspace_root, output_root=output_root))
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
