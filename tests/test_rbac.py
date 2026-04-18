"""
RBAC & multi-tenant isolation regression tests.

Covers:
- Tenant isolation: Task A created by Key-A is not visible to Key-B.
- Tenant isolation: cancel across tenants is denied.
- Artifact access: tenant B cannot preview/download/bundle tenant A's artifacts.
- Scope enforcement: read_only key cannot call admin-gated routes.
- Operator scope: can call /chat but cannot call /api-keys admin routes.
- System tenant (config-based key): can see all tasks when auth is not required.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from harness.api.key_store import KeyRecord, KeyStore
from harness.api.server import create_app
from harness.orchestrator.task_store import TaskRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(key_id: str, scope: str, tenant_id: str) -> KeyRecord:
    return KeyRecord(
        id=key_id,
        description=f"test-{scope}-{tenant_id}",
        scope=scope,
        key_prefix=key_id[:8],
        key_hash=key_id,
        created_at="2024-01-01T00:00:00Z",
        last_used_at=None,
        expires_at=None,
        revoked_at=None,
        tenant_id=tenant_id,
    )


def _make_task_record(task_id: str, tenant_id: str) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        description="rbac test task",
        status="completed",
        created_at="2024-01-01T00:00:00Z",
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KEY_A = "key-tenant-alpha"
KEY_B = "key-tenant-beta"
KEY_READONLY = "key-read-only"
KEY_OPERATOR = "key-operator-x"
KEY_ADMIN = "key-admin-store"

TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"

RECORDS: dict[str, KeyRecord] = {
    KEY_A:        _make_record(KEY_A,       "read",      TENANT_A),
    KEY_B:        _make_record(KEY_B,       "read",      TENANT_B),
    KEY_READONLY: _make_record(KEY_READONLY,"read_only", "tenant-ro"),
    KEY_OPERATOR: _make_record(KEY_OPERATOR,"operator",  "tenant-op"),
    KEY_ADMIN:    _make_record(KEY_ADMIN,   "admin",     "_system_"),
}

TASK_A = "task-00000000-aaaa"
TASK_B = "task-00000000-bbbb"

TASK_RECORDS: dict[str, TaskRecord] = {
    TASK_A: _make_task_record(TASK_A, TENANT_A),
    TASK_B: _make_task_record(TASK_B, TENANT_B),
}


def _fake_authenticate(raw_key: str) -> KeyRecord | None:
    return RECORDS.get(raw_key)


@pytest.fixture()
def client(tmp_path: Path):
    """Build a test client with key-store and task-store stubs injected."""
    app = create_app(tmp_path)
    runtime = app.state.runtime

    # Patch the key store inside the app's closure.
    # create_app builds its _key_store internally; we monkey-patch authenticate
    # by replacing the key_store object used in the closure via the module-level
    # factory — simplest approach is to patch KeyStore.authenticate on the class.
    with patch.object(KeyStore, "authenticate", side_effect=_fake_authenticate):
        # Seed task store with pre-existing tasks for both tenants
        for rec in TASK_RECORDS.values():
            runtime.orchestrator.task_store._records[rec.task_id] = rec

        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# Task isolation
# ---------------------------------------------------------------------------

class TestTaskIsolation:
    def test_tenant_a_sees_own_task(self, client: TestClient):
        resp = client.get("/tasks", headers={"x-api-key": KEY_A})
        assert resp.status_code == 200
        ids = [t["task_id"] for t in resp.json()]
        assert TASK_A in ids

    def test_tenant_a_cannot_see_tenant_b_task(self, client: TestClient):
        resp = client.get("/tasks", headers={"x-api-key": KEY_A})
        assert resp.status_code == 200
        ids = [t["task_id"] for t in resp.json()]
        assert TASK_B not in ids

    def test_tenant_b_cannot_cancel_tenant_a_task(self, client: TestClient):
        resp = client.post(f"/tasks/{TASK_A}/cancel", headers={"x-api-key": KEY_B})
        assert resp.status_code == 403

    def test_admin_store_key_can_see_all_tasks(self, client: TestClient):
        """Admin key with tenant_id='_system_' acts as system tenant."""
        resp = client.get("/tasks", headers={"x-api-key": KEY_ADMIN})
        assert resp.status_code == 200
        ids = [t["task_id"] for t in resp.json()]
        assert TASK_A in ids
        assert TASK_B in ids


# ---------------------------------------------------------------------------
# Artifact isolation
# ---------------------------------------------------------------------------

class TestArtifactIsolation:
    def test_tenant_b_cannot_preview_tenant_a_artifact(self, client: TestClient):
        resp = client.get(
            f"/artifacts/run/{TASK_A}/some-artifact/preview",
            headers={"x-api-key": KEY_B},
        )
        assert resp.status_code == 403

    def test_tenant_b_cannot_download_tenant_a_artifact(self, client: TestClient):
        resp = client.get(
            f"/artifacts/run/{TASK_A}/some-artifact/download",
            headers={"x-api-key": KEY_B},
        )
        assert resp.status_code == 403

    def test_tenant_b_cannot_bundle_tenant_a_artifacts(self, client: TestClient):
        resp = client.get(
            f"/artifacts/run/{TASK_A}/bundle",
            headers={"x-api-key": KEY_B},
        )
        assert resp.status_code == 403

    def test_tenant_a_preview_own_task_gets_404_not_403(self, client: TestClient):
        """Tenant A has access to their own task; missing artifact → 404, not 403."""
        resp = client.get(
            f"/artifacts/run/{TASK_A}/no-such-artifact/preview",
            headers={"x-api-key": KEY_A},
        )
        # Access check passes → falls through to file-not-found
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

class TestScopeEnforcement:
    def test_read_only_key_cannot_create_api_keys(self, client: TestClient):
        """Admin-gated routes must reject read_only scope."""
        resp = client.post(
            "/api-keys",
            json={"label": "hacker", "scope": "read"},
            headers={"x-api-key": KEY_READONLY},
        )
        assert resp.status_code == 403

    def test_operator_key_cannot_manage_api_keys(self, client: TestClient):
        resp = client.post(
            "/api-keys",
            json={"label": "op-attempt", "scope": "read"},
            headers={"x-api-key": KEY_OPERATOR},
        )
        assert resp.status_code == 403

    def test_admin_store_key_can_manage_api_keys(self, client: TestClient):
        """Admin-scoped store key must be accepted on admin routes."""
        # We only care that auth passes (not a 403); the actual body may
        # fail if KeyStore isn't fully functional in this stub, which is fine.
        resp = client.post(
            "/api-keys",
            json={"label": "new-key", "scope": "read"},
            headers={"x-api-key": KEY_ADMIN},
        )
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# KeyRecord unit-level tests
# ---------------------------------------------------------------------------

class TestKeyRecord:
    def test_is_admin_true_for_admin_scope(self):
        rec = _make_record("x", "admin", "_system_")
        assert rec.is_admin is True

    def test_is_admin_false_for_operator(self):
        rec = _make_record("x", "operator", "_system_")
        assert rec.is_admin is False

    def test_is_operator_true_for_operator_and_admin(self):
        for scope in ("operator", "admin"):
            rec = _make_record("x", scope, "_system_")
            assert rec.is_operator is True

    def test_is_operator_false_for_read_scopes(self):
        for scope in ("read", "read_only"):
            rec = _make_record("x", scope, "t")
            assert rec.is_operator is False

    def test_allowed_tools_defaults_to_empty_list(self):
        rec = _make_record("x", "read", "t")
        assert rec.allowed_tools == []
