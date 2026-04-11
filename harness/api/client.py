from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(slots=True)
class HarnessApiClient:
    """Helper wrapper for incident, diagnosis, market, and UI overview workflows."""

    base_url: str
    api_key: str | None = None
    admin_api_key: str | None = None
    timeout_s: float = 30.0
    client: Any | None = None
    _owns_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._owns_client = self.client is None
        if self.client is None:
            self.client = httpx.Client(base_url=self.base_url.rstrip("/"), timeout=self.timeout_s)

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    def __enter__(self) -> "HarnessApiClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _headers(self, *, admin: bool = False) -> dict[str, str]:
        key = self.admin_api_key if admin and self.admin_api_key else self.api_key
        if not key:
            return {}
        return {"x-api-key": key}

    def get_incident_by_execution_id(
        self,
        *,
        execution_id: str,
        after: str | None = None,
        before: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "execution_id": execution_id,
            "offset": max(0, offset),
            "limit": max(1, min(limit, 500)),
        }
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        response = self.client.get("/reports/incident", params=params, headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    def export_diagnosis_snapshot(
        self,
        *,
        path: str,
        source: str | None = None,
        agent_id: str | None = None,
        skill_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": path,
            "offset": max(0, offset),
            "limit": max(1, min(limit, 500)),
        }
        if source is not None:
            payload["source"] = source
        if agent_id is not None:
            payload["agent_id"] = agent_id
        if skill_id is not None:
            payload["skill_id"] = skill_id
        if after is not None:
            payload["after"] = after
        if before is not None:
            payload["before"] = before
        response = self.client.post("/diagnostics/emergency/export", json=payload, headers=self._headers(admin=True))
        response.raise_for_status()
        return dict(response.json())

    def verify_diagnosis_snapshot(self, *, path: str) -> dict[str, Any]:
        response = self.client.post(
            "/diagnostics/emergency/verify",
            json={"path": path},
            headers=self._headers(),
        )
        response.raise_for_status()
        return dict(response.json())

    def sync_remote_market(self, *, source: str, force: bool = False) -> dict[str, Any]:
        response = self.client.post(
            "/skills/market/remote/sync",
            json={"source": source, "force": force},
            headers=self._headers(admin=True),
        )
        response.raise_for_status()
        return dict(response.json())

    def get_market_remote_status(self) -> dict[str, Any]:
        response = self.client.get("/skills/market/remote/status", headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    def get_ui_market_overview(self) -> dict[str, Any]:
        response = self.client.get("/ui/market/overview", headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    def get_ui_ingestion_overview(self) -> dict[str, Any]:
        response = self.client.get("/ui/ingestion/overview", headers=self._headers())
        response.raise_for_status()
        return dict(response.json())
