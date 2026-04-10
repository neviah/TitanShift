from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from typing import Callable


@dataclass(slots=True)
class ScheduledJob:
    job_id: str
    callback: Callable[[], Any]
    description: str = ""
    interval_seconds: int = 60
    enabled: bool = True
    max_failures: int = 3
    run_count: int = 0
    failure_count: int = 0
    last_run_at: str | None = None
    last_error: str | None = None


class Scheduler:
    """Phase 1 scheduler: explicit job registry and manual heartbeat/tick."""

    def __init__(self) -> None:
        self.jobs: dict[str, ScheduledJob] = {}
        self.heartbeat_count: int = 0
        self.last_heartbeat_at: str | None = None

    def register_job(self, job: ScheduledJob) -> None:
        self.jobs[job.job_id] = job

    def remove_job(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)

    def set_enabled(self, job_id: str, enabled: bool) -> ScheduledJob | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job.enabled = enabled
        return job

    def get_job(self, job_id: str) -> ScheduledJob | None:
        return self.jobs.get(job_id)

    def heartbeat(self) -> dict[str, Any]:
        self.heartbeat_count += 1
        self.last_heartbeat_at = datetime.now(timezone.utc).isoformat()
        return {
            "heartbeat_count": self.heartbeat_count,
            "last_heartbeat_at": self.last_heartbeat_at,
            "job_count": len(self.jobs),
        }

    async def tick(self) -> dict[str, Any]:
        ran: list[str] = []
        failed: list[str] = []
        auto_disabled: list[str] = []
        for job in self.jobs.values():
            if not job.enabled:
                continue
            try:
                result = job.callback()
                if hasattr(result, "__await__"):
                    await result
                job.run_count += 1
                job.failure_count = 0
                job.last_error = None
                job.last_run_at = datetime.now(timezone.utc).isoformat()
                ran.append(job.job_id)
            except Exception as exc:
                job.failure_count += 1
                job.last_error = str(exc)
                job.last_run_at = datetime.now(timezone.utc).isoformat()
                failed.append(job.job_id)
                if job.failure_count >= max(1, job.max_failures):
                    job.enabled = False
                    auto_disabled.append(job.job_id)
        return {
            "ran_jobs": ran,
            "failed_jobs": failed,
            "auto_disabled_jobs": auto_disabled,
            "job_count": len(self.jobs),
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for job in sorted(self.jobs.values(), key=lambda j: j.job_id):
            rows.append(
                {
                    "job_id": job.job_id,
                    "description": job.description,
                    "interval_seconds": job.interval_seconds,
                    "enabled": job.enabled,
                    "max_failures": job.max_failures,
                    "run_count": job.run_count,
                    "failure_count": job.failure_count,
                    "last_run_at": job.last_run_at,
                    "last_error": job.last_error,
                }
            )
        return rows
