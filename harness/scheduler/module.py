from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from typing import Callable


@dataclass(slots=True)
class ScheduledJob:
    job_id: str
    callback: Callable[[], Any]
    description: str = ""
    schedule_type: str = "interval"
    interval_seconds: int = 60
    cron: str | None = None
    enabled: bool = True
    timeout_s: float | None = None
    max_failures: int = 3
    run_count: int = 0
    failure_count: int = 0
    last_run_at: str | None = None
    last_error: str | None = None
    is_running: bool = False


class Scheduler:
    """Phase 3 scheduler: interval/cron jobs, heartbeat tracking, and failure guardrails."""

    def __init__(self) -> None:
        self.jobs: dict[str, ScheduledJob] = {}
        self.heartbeat_count: int = 0
        self.last_heartbeat_at: str | None = None
        self.heartbeat_timeout_s: float = 120.0
        self.heartbeat_alert_active: bool = False

    def set_heartbeat_timeout(self, timeout_s: float) -> None:
        self.heartbeat_timeout_s = max(1.0, float(timeout_s))

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None

    @staticmethod
    def _matches_cron_field(field: str, value: int) -> bool:
        token = field.strip()
        if token == "*":
            return True
        if token.startswith("*/"):
            try:
                step = int(token[2:])
                return step > 0 and (value % step == 0)
            except ValueError:
                return False
        for part in token.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    start_raw, end_raw = part.split("-", maxsplit=1)
                    start = int(start_raw)
                    end = int(end_raw)
                except ValueError:
                    continue
                if start <= value <= end:
                    return True
                continue
            try:
                if int(part) == value:
                    return True
            except ValueError:
                continue
        return False

    def _cron_due(self, job: ScheduledJob, now: datetime) -> bool:
        if not job.cron:
            return False
        fields = job.cron.split()
        if len(fields) != 5:
            return False

        minute, hour, day, month, weekday = fields
        py_weekday = (now.weekday() + 1) % 7
        if not all(
            [
                self._matches_cron_field(minute, now.minute),
                self._matches_cron_field(hour, now.hour),
                self._matches_cron_field(day, now.day),
                self._matches_cron_field(month, now.month),
                self._matches_cron_field(weekday, py_weekday),
            ]
        ):
            return False

        if not job.last_run_at:
            return True
        last = self._parse_timestamp(job.last_run_at)
        if last is None:
            return True
        return (
            last.year,
            last.month,
            last.day,
            last.hour,
            last.minute,
        ) != (
            now.year,
            now.month,
            now.day,
            now.hour,
            now.minute,
        )

    def _interval_due(self, job: ScheduledJob, now: datetime) -> bool:
        if job.last_run_at is None:
            return True
        if job.last_error is not None:
            return True
        last = self._parse_timestamp(job.last_run_at)
        if last is None:
            return True
        elapsed = (now - last).total_seconds()
        return elapsed >= max(1, int(job.interval_seconds))

    def _compute_next_run_at(self, job: ScheduledJob, now: datetime) -> str | None:
        if not job.enabled:
            return None

        if job.schedule_type == "cron":
            if not job.cron:
                return None
            probe = now.replace(second=0, microsecond=0)
            for _ in range(0, 8 * 24 * 60):
                probe = probe + timedelta(minutes=1)
                if self._cron_due(job, probe):
                    return probe.isoformat()
            return None

        if job.last_run_at is None:
            return now.isoformat()
        last = self._parse_timestamp(job.last_run_at)
        if last is None:
            return now.isoformat()
        next_at = last + timedelta(seconds=max(1, int(job.interval_seconds)))
        if next_at < now:
            next_at = now
        return next_at.isoformat()

    def _job_due(self, job: ScheduledJob, now: datetime) -> bool:
        if job.schedule_type == "cron":
            return self._cron_due(job, now)
        return self._interval_due(job, now)

    def _heartbeat_state(self, now: datetime) -> tuple[bool, float | None, bool, bool]:
        last = self._parse_timestamp(self.last_heartbeat_at)
        if last is None:
            return False, None, False, False
        lag = max(0.0, (now - last).total_seconds())
        missed = lag > self.heartbeat_timeout_s
        newly_missed = missed and not self.heartbeat_alert_active
        recovered = (not missed) and self.heartbeat_alert_active
        self.heartbeat_alert_active = missed
        return missed, lag, newly_missed, recovered

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
        now = datetime.now(timezone.utc)
        missed_heartbeat, heartbeat_lag_s, newly_missed, recovered = self._heartbeat_state(now)
        ran: list[str] = []
        failed: list[str] = []
        timed_out: list[str] = []
        auto_disabled: list[str] = []
        for job in self.jobs.values():
            if not job.enabled:
                continue
            if not self._job_due(job, now):
                continue
            try:
                job.is_running = True
                result = job.callback()
                if inspect.isawaitable(result):
                    execution = result
                else:
                    execution = asyncio.to_thread(lambda: result)

                if job.timeout_s is not None:
                    await asyncio.wait_for(execution, timeout=job.timeout_s)
                else:
                    await execution
                job.run_count += 1
                job.failure_count = 0
                job.last_error = None
                job.last_run_at = datetime.now(timezone.utc).isoformat()
                ran.append(job.job_id)
            except TimeoutError:
                job.failure_count += 1
                job.last_error = f"Timed out after {job.timeout_s}s"
                job.last_run_at = datetime.now(timezone.utc).isoformat()
                failed.append(job.job_id)
                timed_out.append(job.job_id)
                if job.failure_count >= max(1, job.max_failures):
                    job.enabled = False
                    auto_disabled.append(job.job_id)
            except Exception as exc:
                job.failure_count += 1
                job.last_error = str(exc)
                job.last_run_at = datetime.now(timezone.utc).isoformat()
                failed.append(job.job_id)
                if job.failure_count >= max(1, job.max_failures):
                    job.enabled = False
                    auto_disabled.append(job.job_id)
            finally:
                job.is_running = False
        return {
            "ran_jobs": ran,
            "failed_jobs": failed,
            "timed_out_jobs": timed_out,
            "auto_disabled_jobs": auto_disabled,
            "job_count": len(self.jobs),
            "missed_heartbeat": missed_heartbeat,
            "newly_missed_heartbeat": newly_missed,
            "recovered_heartbeat": recovered,
            "heartbeat_lag_s": heartbeat_lag_s,
            "heartbeat_timeout_s": self.heartbeat_timeout_s,
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        for job in sorted(self.jobs.values(), key=lambda j: j.job_id):
            rows.append(
                {
                    "job_id": job.job_id,
                    "description": job.description,
                    "schedule_type": job.schedule_type,
                    "interval_seconds": job.interval_seconds,
                    "cron": job.cron,
                    "enabled": job.enabled,
                    "timeout_s": job.timeout_s,
                    "max_failures": job.max_failures,
                    "run_count": job.run_count,
                    "failure_count": job.failure_count,
                    "last_run_at": job.last_run_at,
                    "last_error": job.last_error,
                    "is_running": job.is_running,
                    "next_run_at": self._compute_next_run_at(job, now),
                }
            )
        return rows
