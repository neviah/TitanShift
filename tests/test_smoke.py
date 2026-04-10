from pathlib import Path

from harness.api.server import create_app
from harness.model.adapter import ModelRegistry
from harness.runtime.config import ConfigManager


def test_defaults_load() -> None:
    cfg = ConfigManager(Path("."))
    assert cfg.get("memory.graph_backend") == "networkx"
    assert cfg.get("tools.deny_all_by_default") is True


def test_api_factory() -> None:
    app = create_app(Path(".").resolve())
    assert app.title == "TitantShift Harness API"


def test_model_backends_registered() -> None:
    cfg = ConfigManager(Path("."))
    registry = ModelRegistry.from_config(cfg)
    assert "local_stub" in registry.adapters
    assert "lmstudio" in registry.adapters
