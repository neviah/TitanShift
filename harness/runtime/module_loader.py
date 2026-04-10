from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


@dataclass(slots=True)
class LoadedModule:
    name: str
    module: ModuleType
    capabilities: list[str]
    hooks: dict[str, Any]


class ModuleLoader:
    """Discovers and registers pluggable modules."""

    def __init__(self, modules_root: Path) -> None:
        self.modules_root = modules_root
        self._loaded: dict[str, LoadedModule] = {}

    def register_module(self, name: str, capabilities: list[str], hooks: dict[str, Any]) -> None:
        self._loaded[name] = LoadedModule(
            name=name,
            module=importlib.import_module(name),
            capabilities=capabilities,
            hooks=hooks,
        )

    def list_modules(self) -> list[str]:
        return sorted(self._loaded.keys())

    def discover_modules(self) -> list[str]:
        discovered: list[str] = []
        if not self.modules_root.exists():
            return discovered
        for mod in pkgutil.iter_modules([str(self.modules_root)]):
            discovered.append(mod.name)
        return sorted(discovered)

    def load_from_package(self, package_name: str) -> None:
        module = importlib.import_module(package_name)
        register = getattr(module, "register", None)
        if callable(register):
            register(self)

    def reload_module(self, name: str) -> None:
        loaded = self._loaded.get(name)
        if not loaded:
            raise KeyError(f"Module not loaded: {name}")
        loaded.module = importlib.reload(loaded.module)
