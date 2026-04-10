from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class ScheduledJob:
    job_id: str
    callback: Callable[[], None]


class Scheduler:
    """Phase 1 stub with registration only, no timing loop yet."""

    def __init__(self) -> None:
        self.jobs: dict[str, ScheduledJob] = {}

    def register_job(self, job: ScheduledJob) -> None:
        self.jobs[job.job_id] = job

    def remove_job(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)
