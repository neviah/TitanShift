from __future__ import annotations

from dataclasses import dataclass, field
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

    def query_neighbors(self, node_id: str) -> list[str]: ...
