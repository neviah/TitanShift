from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str


def _check_command(name: str, *, required: bool = True) -> CheckResult:
    resolved = shutil.which(name)
    if resolved:
        return CheckResult(name=name, ok=True, required=required, detail=f"found at {resolved}")
    return CheckResult(name=name, ok=False, required=required, detail="not found on PATH")


def _check_reportlab(*, required: bool = True) -> CheckResult:
    available = importlib.util.find_spec("reportlab") is not None
    if available:
        return CheckResult(name="python:reportlab", ok=True, required=required, detail="importable")
    return CheckResult(
        name="python:reportlab",
        ok=False,
        required=required,
        detail="missing (install with pip install reportlab)",
    )


def _check_remotion(project_path: Path, *, required: bool = True, timeout_s: int = 60) -> CheckResult:
    package_json = project_path / "package.json"
    if not package_json.exists():
        return CheckResult(
            name="remotion-cli",
            ok=False,
            required=required,
            detail=f"package.json not found in {project_path}",
        )

    npm_bin = shutil.which("npm")
    if not npm_bin:
        return CheckResult(
            name="remotion-cli",
            ok=False,
            required=required,
            detail="npm is not available on PATH",
        )

    cmd = [npm_bin, "exec", "remotion", "--", "versions"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - defensive branch
        return CheckResult(
            name="remotion-cli",
            ok=False,
            required=required,
            detail=f"execution failed: {exc}",
        )

    if proc.returncode == 0:
        version = (proc.stdout or proc.stderr).strip().splitlines()
        resolved = version[0] if version else "version check ok"
        return CheckResult(name="remotion-cli", ok=True, required=required, detail=resolved)

    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    detail = stderr or stdout or f"exit code {proc.returncode}"
    return CheckResult(name="remotion-cli", ok=False, required=required, detail=detail)


def _check_testing_root(testing_root: Path, *, required: bool = True) -> CheckResult:
    try:
        testing_root.mkdir(parents=True, exist_ok=True)
        probe = testing_root / ".write_probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return CheckResult(name="testing-root", ok=True, required=required, detail=f"writable: {testing_root}")
    except Exception as exc:  # pragma: no cover - defensive branch
        return CheckResult(name="testing-root", ok=False, required=required, detail=f"not writable: {exc}")


def run_preflight(
    workspace_root: Path,
    remotion_project_path: Path,
    testing_root: Path,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.append(_check_command("python", required=True))
    checks.append(_check_command("node", required=True))
    checks.append(_check_command("npm", required=True))
    checks.append(_check_command("ffmpeg", required=True))
    checks.append(_check_reportlab(required=True))
    checks.append(_check_remotion(remotion_project_path, required=True))
    checks.append(_check_testing_root(testing_root, required=True))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight checks for TitanShift matrix execution (video + artifact workflows)."
    )
    parser.add_argument("--workspace-root", default=".", help="Workspace root path (default: .)")
    parser.add_argument(
        "--remotion-project",
        default="frontend",
        help="Path to Remotion project relative to workspace root (default: frontend)",
    )
    parser.add_argument("--testing-root", default="Testing", help="Testing artifact root (default: Testing)")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary",
    )

    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    remotion_project = Path(args.remotion_project)
    remotion_project_path = (workspace_root / remotion_project).resolve() if not remotion_project.is_absolute() else remotion_project.resolve()
    testing_root = Path(args.testing_root)
    testing_root_path = (workspace_root / testing_root).resolve() if not testing_root.is_absolute() else testing_root.resolve()

    checks = run_preflight(
        workspace_root=workspace_root,
        remotion_project_path=remotion_project_path,
        testing_root=testing_root_path,
    )

    blocking_failures = [c for c in checks if c.required and not c.ok]

    if args.json:
        payload = {
            "workspace_root": str(workspace_root),
            "remotion_project": str(remotion_project_path),
            "testing_root": str(testing_root_path),
            "checks": [asdict(c) for c in checks],
            "ok": len(blocking_failures) == 0,
            "blocking_failure_count": len(blocking_failures),
        }
        print(json.dumps(payload, indent=2))
    else:
        print("TitanShift testing preflight")
        print(f"workspace_root={workspace_root}")
        print(f"remotion_project={remotion_project_path}")
        print(f"testing_root={testing_root_path}")
        for check in checks:
            status = "PASS" if check.ok else ("FAIL" if check.required else "WARN")
            req = "required" if check.required else "optional"
            print(f"[{status}] {check.name} ({req}) - {check.detail}")
        print(f"blocking_failure_count={len(blocking_failures)}")

    return 1 if blocking_failures else 0


if __name__ == "__main__":
    sys.exit(main())
