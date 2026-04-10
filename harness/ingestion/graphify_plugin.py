from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class GraphifyPlugin:
    enabled: bool = False

    def ingest_text(self, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Optional plugin stub to integrate graphify output mapping later."""
        if not self.enabled:
            return {"enabled": False, "nodes": [], "edges": []}
        return {
            "enabled": True,
            "nodes": [{"id": "placeholder", "type": "concept", "text": text[:80]}],
            "edges": [],
            "metadata": metadata or {},
        }
