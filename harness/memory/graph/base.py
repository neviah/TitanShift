from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from typing import Protocol


@dataclass(slots=True)
class GraphNode:
    node_id: str
    node_type: str
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    edge_type: str
    properties: dict[str, str] = field(default_factory=dict)


class GraphBackend(Protocol):
    def add_node(self, node: GraphNode) -> None: ...

    def add_edge(self, edge: GraphEdge) -> None: ...

    def has_node(self, node_id: str) -> bool: ...

    def has_edge(self, source: str, target: str) -> bool: ...

    def query_neighbors(self, node_id: str) -> list[str]: ...

    def search_nodes(self, query: str, node_type: str | None = None, limit: int = 20) -> list[dict[str, Any]]: ...

    def export_snapshot(self) -> dict[str, Any]: ...

    def import_snapshot(self, snapshot: dict[str, Any], *, clear_existing: bool = False) -> dict[str, int]: ...
