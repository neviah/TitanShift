"""
Service lifecycle management for generated repo adapters.

Handles starting, stopping, and health-checking external services that back HTTP/CLI adapters.
Provides generic launcher interface supporting docker, npm, python, binary, subprocess patterns.
"""

import asyncio
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass
class ServiceLaunchConfig:
    """Configuration for launching a service."""

    service_id: str
    start_strategy: str  # docker | npm | python | binary | subprocess
    start_command: str
    start_args: list[str] = field(default_factory=list)
    working_dir: str | None = None
    healthcheck_url: str | None = None  # e.g., http://127.0.0.1:9377/health
    healthcheck_timeout_s: float = 5.0
    startup_timeout_s: float = 30.0
    retry_interval_s: float = 1.0
    max_retries: int = 5


@dataclass
class ServiceStatus:
    """Current status of a managed service."""

    service_id: str
    status: str  # starting | running | stopped | failed
    last_checked: str  # ISO timestamp
    last_error: str | None = None
    started_at: str | None = None  # ISO timestamp when service actually started
    uptime_s: float = 0.0  # Time since started


class ServiceManager:
    """Manages service lifecycle for repo-generated adapters."""

    def __init__(self):
        self.services: dict[str, ServiceLaunchConfig] = {}
        self.service_statuses: dict[str, ServiceStatus] = {}
        self._service_processes: dict[str, subprocess.Popen] = {}

    def register_service(self, config: ServiceLaunchConfig) -> None:
        """Register a service that can be launched on-demand."""
        self.services[config.service_id] = config
        self.service_statuses[config.service_id] = ServiceStatus(
            service_id=config.service_id,
            status="stopped",
            last_checked=datetime.now(timezone.utc).isoformat(),
        )

    def unregister_service(self, service_id: str) -> None:
        """Remove a service from management and stop it if needed."""
        proc = self._service_processes.pop(service_id, None)
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.services.pop(service_id, None)
        self.service_statuses.pop(service_id, None)

    async def check_health(self, service_id: str) -> tuple[bool, str | None]:
        """
        Check if a service is healthy via its healthcheck endpoint.
        Returns (is_healthy, error_reason).
        """
        config = self.services.get(service_id)
        if not config or not config.healthcheck_url:
            return False, "No healthcheck configured"

        try:
            async with httpx.AsyncClient(timeout=config.healthcheck_timeout_s) as client:
                response = await client.get(config.healthcheck_url)
                is_healthy = response.status_code < 400
                self.service_statuses[service_id].last_checked = datetime.now(timezone.utc).isoformat()
                if is_healthy:
                    return True, None
                else:
                    return False, f"HTTP {response.status_code}"
        except asyncio.TimeoutError:
            return False, "Healthcheck timeout"
        except Exception as exc:
            return False, str(exc)

    async def start_service(self, service_id: str) -> tuple[bool, str | None]:
        """
        Start a service using the configured strategy.
        Returns (success, error_reason).
        """
        config = self.services.get(service_id)
        if not config:
            return False, f"Service not registered: {service_id}"

        status = self.service_statuses[service_id]
        if status.status == "running":
            # Already running, just verify health
            healthy, err = await self.check_health(service_id)
            if healthy:
                return True, None
            # Health check failed, will retry

        status.status = "starting"
        status.last_checked = datetime.now(timezone.utc).isoformat()

        try:
            if config.start_strategy == "subprocess":
                return await self._start_subprocess(config)
            elif config.start_strategy in {"npm", "python", "binary"}:
                return await self._start_subprocess(config)
            elif config.start_strategy == "docker":
                return False, "Docker strategy not yet implemented"
            else:
                return False, f"Unknown start strategy: {config.start_strategy}"
        except Exception as exc:
            status.status = "failed"
            status.last_error = str(exc)
            return False, f"Service startup failed: {exc}"

    async def _start_subprocess(self, config: ServiceLaunchConfig) -> tuple[bool, str | None]:
        """Start a service using subprocess."""
        parts = shlex.split(config.start_command, posix=os.name != "nt")
        args = parts + config.start_args

        try:
            # Start the process
            proc = subprocess.Popen(
                args,
                cwd=config.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._service_processes[config.service_id] = proc
            status = self.service_statuses[config.service_id]
            status.started_at = datetime.now(timezone.utc).isoformat()

            # Wait for health check to pass or timeout
            retry_count = 0
            while retry_count < config.max_retries:
                await asyncio.sleep(config.retry_interval_s)
                healthy, err = await self.check_health(config.service_id)
                if healthy:
                    status.status = "running"
                    return True, None
                retry_count += 1

            # Health checks exhausted
            status.status = "failed"
            status.last_error = f"Health checks failed after {config.max_retries} attempts"
            return False, status.last_error
        except Exception as exc:
            status = self.service_statuses[config.service_id]
            status.status = "failed"
            status.last_error = str(exc)
            return False, str(exc)

    async def stop_service(self, service_id: str) -> tuple[bool, str | None]:
        """Stop a running service."""
        if service_id not in self.service_statuses:
            return False, f"Service not registered: {service_id}"

        proc = self._service_processes.pop(service_id, None)
        if proc:
            try:
                proc.terminate()
                await asyncio.sleep(0.5)
                if proc.poll() is None:
                    proc.kill()
            except Exception as exc:
                return False, str(exc)

        status = self.service_statuses[service_id]
        status.status = "stopped"
        status.started_at = None
        return True, None

    def get_status(self, service_id: str) -> ServiceStatus | None:
        """Get current status of a service."""
        return self.service_statuses.get(service_id)

    def get_all_statuses(self) -> list[ServiceStatus]:
        """Get status of all managed services."""
        return list(self.service_statuses.values())
