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
    run_count: int = 0
    last_run_at: str | None = None


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
        for job in self.jobs.values():
            if not job.enabled:
                continue
            result = job.callback()
            if hasattr(result, "__await__"):
                await result
            job.run_count += 1
            job.last_run_at = datetime.now(timezone.utc).isoformat()
            ran.append(job.job_id)
        return {"ran_jobs": ran, "job_count": len(self.jobs)}

    def list_jobs(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for job in sorted(self.jobs.values(), key=lambda j: j.job_id):
            rows.append(
                {
                    "job_id": job.job_id,
                    "description": job.description,
                    "interval_seconds": job.interval_seconds,
                    "enabled": job.enabled,
                    "run_count": job.run_count,
                    "last_run_at": job.last_run_at,
                }
            )
        return rows
