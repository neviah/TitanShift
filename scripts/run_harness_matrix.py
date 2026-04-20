from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class MatrixCase:
    suite: str
    case_id: str
    title: str
    prompt: str
    workflow_mode: str = "lightning"
    timeout_s: int = 300
    expects_success: bool = True
    retries: int = 0
    retry_backoff_s: float = 2.0
    cancel_on_timeout: bool = True


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _http_json(url: str, payload: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _submit_run(base_url: str, payload: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    return _http_json(f"{base_url}/runs", payload, timeout_s=timeout_s)


def _post_empty(url: str, timeout_s: int) -> dict[str, Any]:
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}


def _cancel_task(base_url: str, task_id: str) -> dict[str, Any] | None:
    if not task_id:
        return None
    try:
        return _post_empty(f"{base_url}/tasks/{task_id}/cancel", timeout_s=20)
    except Exception:
        return None


def _poll_run(base_url: str, run_id: str, timeout_s: int, poll_interval_s: float = 2.0) -> tuple[dict[str, Any] | None, str | None]:
    started = time.time()
    last_status: dict[str, Any] | None = None
    while (time.time() - started) <= timeout_s:
        try:
            status = _http_get_json(f"{base_url}/runs/{run_id}", timeout_s=30)
        except Exception as exc:  # pragma: no cover
            return None, str(exc)
        last_status = status
        state = str(status.get("state") or "").lower()
        if state in {"completed", "failed", "timeout", "cancelled"}:
            return status, None
        time.sleep(poll_interval_s)
    return last_status, f"run polling exceeded timeout ({timeout_s}s)"


def _http_get_json(url: str, timeout_s: int) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _matrix_cases(run_root: Path) -> list[MatrixCase]:
    p1_target = (run_root / "P1_frontend_quality" / "landing" / "index.html").as_posix()
    p2_target_dir = (run_root / "P2_web_file_integrity").as_posix()
    p2_target = (run_root / "P2_web_file_integrity" / "reddit_capture.txt").as_posix()
    p4_video_target = (run_root / "P4_creator_use_cases" / "video_generation").as_posix()

    return [
        MatrixCase(
            suite="P0_core_reliability",
            case_id="mode_lightning",
            title="Mode routing lightning",
            workflow_mode="lightning",
            timeout_s=120,
            prompt="Create directory Testing/P0_core_reliability and then create file Testing/P0_core_reliability/mode_lightning.txt with one line: lightning mode ok",
        ),
        MatrixCase(
            suite="P0_core_reliability",
            case_id="mode_superpowered",
            title="Mode routing superpowered",
            workflow_mode="superpowered",
            timeout_s=900,
            retries=0,
            retry_backoff_s=4.0,
            prompt=(
                f"Your only job: create the directory {(run_root / 'P0_core_reliability').as_posix()} "
                f"and then write exactly one file {(run_root / 'P0_core_reliability' / 'mode_superpowered.txt').as_posix()} "
                "whose entire content is one line: superpowered mode ok\n"
                "Use create_directory and write_file. Do not create any other files or directories."
            ),
        ),
        MatrixCase(
            suite="P1_frontend_quality",
            case_id="landing_single_file",
            title="Single-file landing quality",
            workflow_mode="superpowered",
            timeout_s=1200,
            retries=0,
            retry_backoff_s=6.0,
            prompt=(
                f"Create the directory {(run_root / 'P1_frontend_quality' / 'landing').as_posix()} "
                f"and write one self-contained HTML file to {p1_target}. "
                "The file must have embedded CSS, a responsive layout, and at least one inline SVG decorative element. "
                "Use create_directory then write_file. Do not create any other files."
            ),
        ),
        MatrixCase(
            suite="P2_web_file_integrity",
            case_id="fetch_then_write",
            title="Web fetch then write",
            workflow_mode="lightning",
            timeout_s=900,
            prompt=(
                f"Create the directory {p2_target_dir} using create_directory. "
                "Then use web_browse or web_fetch to open https://www.reddit.com and find one post URL. "
                f"Use write_file to write that URL as a single line to {p2_target}. "
                "Then use read_file to confirm the file contains the URL and return its content."
            ),
        ),
        MatrixCase(
            suite="P3_skill_activation",
            case_id="writing_plan_skill",
            title="Skill activation sanity",
            workflow_mode="superpowered",
            timeout_s=900,
            prompt=(
                f"Create the directory {(run_root / 'P3_skill_activation').as_posix()} using create_directory. "
                f"Write a markdown project rollout plan to {(run_root / 'P3_skill_activation' / 'plan.md').as_posix()} "
                "that contains a timeline, risks, and mitigations section. "
                "Use write_file. Do not create any other files or directories."
            ),
        ),
        MatrixCase(
            suite="P4_creator_use_cases",
            case_id="video_remotion_render",
            title="Remotion MP4 render",
            workflow_mode="superpowered",
            timeout_s=1500,
            retries=0,
            retry_backoff_s=8.0,
            prompt=(
                f"Create the directory {p4_video_target} using create_directory. "
                "Then call the generate_remotion_video tool with these exact arguments: "
                "composition_id=HelloVideo, project_path=frontend, entry=remotion/index.tsx, "
                f"target_path={p4_video_target}. "
                "Return the tool result output verbatim. Do not do anything else."
            ),
        ),
        MatrixCase(
            suite="P5_regression_gate",
            case_id="artifact_flood_guard",
            title="Artifact flood guard sampling",
            workflow_mode="lightning",
            timeout_s=300,
            prompt=(
                "Create Testing/P5_regression_gate/flood_guard.txt with one line confirming all generated artifacts "
                "should remain under Testing/."
            ),
        ),
    ]


def run_matrix(base_url: str, workspace_root: Path, output_root: Path, suites: set[str]) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    matrix_run_id = f"matrix-{_now_stamp()}"
    run_root = (output_root / matrix_run_id).resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    cases = [c for c in _matrix_cases(run_root) if c.suite in suites]
    results: list[dict[str, Any]] = []

    for case in cases:
        case_dir = run_root / case.suite / case.case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {
            "prompt": case.prompt,
            "workflow_mode": case.workflow_mode,
            "model_backend": "lmstudio",
        }
        if case.workflow_mode == "superpowered":
            payload["spec_approved"] = True
            payload["plan_approved"] = True
            payload["plan_tasks"] = [{
                "title": case.title,
                "description": case.prompt,
                "implementer_status": "DONE",
                "spec_review_passed": True,
                "code_review_passed": True,
                "verification_passed": True,
            }]

        started_case = time.time()
        response_payload: dict[str, Any] | None = None
        run_status: dict[str, Any] | None = None
        task_payload: dict[str, Any] | None = None
        request_error = None

        attempt_records: list[dict[str, Any]] = []
        for attempt in range(case.retries + 1):
            attempt_record: dict[str, Any] = {"attempt": attempt + 1}
            api_run_id = ""
            try:
                submit = _submit_run(base_url=base_url, payload=payload, timeout_s=30)
                api_run_id = str(submit.get("run_id") or "").strip()
                attempt_record["submit"] = submit
                if not api_run_id:
                    raise RuntimeError(f"run submission did not return run_id: {submit}")
                run_status, poll_error = _poll_run(base_url=base_url, run_id=api_run_id, timeout_s=case.timeout_s)
                response_payload = {
                    "run_id": api_run_id,
                    "state": (run_status or {}).get("state", "unknown"),
                    "success": ((run_status or {}).get("result") or {}).get("success"),
                    "error": ((run_status or {}).get("result") or {}).get("error"),
                    "response": ((run_status or {}).get("result") or {}).get("response"),
                }
                attempt_record["run_status"] = run_status
                if poll_error:
                    request_error = poll_error
                    attempt_record["poll_error"] = poll_error
                    if case.cancel_on_timeout and "exceeded timeout" in poll_error:
                        attempt_record["cancel"] = _cancel_task(base_url=base_url, task_id=api_run_id)
                else:
                    request_error = None
                try:
                    task_payload = _http_get_json(f"{base_url}/tasks/{api_run_id}", timeout_s=30)
                except Exception:
                    task_payload = None
                attempt_record["task"] = task_payload

                if request_error is None and bool((response_payload or {}).get("success")) == case.expects_success:
                    attempt_records.append(attempt_record)
                    break
            except urllib.error.HTTPError as exc:
                request_error = f"HTTP {exc.code}: {exc.reason}"
                attempt_record["error"] = request_error
            except Exception as exc:  # pragma: no cover
                request_error = str(exc)
                attempt_record["error"] = request_error

            attempt_records.append(attempt_record)
            if attempt < case.retries:
                time.sleep(max(0.0, case.retry_backoff_s))

        elapsed = round(time.time() - started_case, 2)
        task_status = str((task_payload or {}).get("status") or "")
        task_success = (task_payload or {}).get("success")
        response_success = (response_payload or {}).get("success")

        case_pass = request_error is None and bool(response_success) == case.expects_success
        if case.expects_success and task_payload is not None:
            case_pass = case_pass and task_status in {"completed", "cancelled", "failed"}
            if task_success is not None:
                case_pass = case_pass and bool(task_success)

        telemetry = {
            "suite": case.suite,
            "case_id": case.case_id,
            "title": case.title,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "request": payload,
            "response": response_payload,
            "run_status": run_status,
            "task": task_payload,
            "attempts": attempt_records,
            "error": request_error,
            "pass": case_pass,
        }
        _write_json(case_dir / "telemetry.json", telemetry)

        report = {
            "suite": case.suite,
            "case_id": case.case_id,
            "title": case.title,
            "status": "passed" if case_pass else "failed",
            "elapsed_seconds": elapsed,
            "response_success": response_success,
            "task_status": task_status,
            "task_success": task_success,
            "error": request_error,
        }
        _write_json(case_dir / "report.json", report)
        results.append(report)

    completed = datetime.now(timezone.utc)
    passed = sum(1 for r in results if r["status"] == "passed")
    failed = len(results) - passed

    summary = {
        "run_id": matrix_run_id,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "duration_seconds": round((completed - started).total_seconds(), 2),
        "base_url": base_url,
        "output_root": str(run_root).replace("\\", "/"),
        "total_cases": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    _write_json(run_root / "report.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TitanShift matrix suites P0-P5 and write telemetry/report artifacts.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Harness API base URL")
    parser.add_argument("--workspace-root", default=".", help="Workspace root")
    parser.add_argument("--output-root", default="Testing", help="Testing output root")
    parser.add_argument(
        "--suites",
        default="P0_core_reliability,P1_frontend_quality,P2_web_file_integrity,P3_skill_activation,P4_creator_use_cases,P5_regression_gate",
        help="Comma-separated suite ids",
    )

    args = parser.parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = (workspace_root / output_root).resolve()

    suites = {s.strip() for s in args.suites.split(",") if s.strip()}

    summary = run_matrix(
        base_url=args.base_url.rstrip("/"),
        workspace_root=workspace_root,
        output_root=output_root,
        suites=suites,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
