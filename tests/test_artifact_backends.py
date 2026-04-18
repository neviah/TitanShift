from __future__ import annotations

import pytest

from harness.artifacts.backends import ArtifactBackendRegistry
from harness.artifacts.backends import ArtifactRenderRequest
from harness.artifacts.backends import ArtifactRenderResult


@pytest.mark.asyncio
async def test_artifact_backend_registry_registers_and_dispatches() -> None:
    registry = ArtifactBackendRegistry()

    async def fake_backend(request: ArtifactRenderRequest) -> ArtifactRenderResult:
        return ArtifactRenderResult(
            backend=request.backend,
            payload={"ok": True, "generator": request.generator},
            artifacts=[{"artifact_id": "a1", "backend": request.backend}],
        )

    registry.register("fake_backend", fake_backend)

    result = await registry.render(
        ArtifactRenderRequest(
            backend="fake_backend",
            generator="unit_test",
            args={"title": "hello"},
        )
    )

    assert registry.list_backends() == ["fake_backend"]
    assert result.backend == "fake_backend"
    assert result.payload["ok"] is True
    assert result.artifacts[0]["backend"] == "fake_backend"


@pytest.mark.asyncio
async def test_artifact_backend_registry_rejects_unknown_backend() -> None:
    registry = ArtifactBackendRegistry()

    with pytest.raises(KeyError, match="Artifact backend not found"):
        await registry.render(
            ArtifactRenderRequest(
                backend="missing_backend",
                generator="unit_test",
                args={},
            )
        )