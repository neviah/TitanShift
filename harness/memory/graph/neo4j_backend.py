from __future__ import annotations

from harness.memory.graph.base import GraphBackend, GraphEdge, GraphNode


class Neo4jGraphBackend(GraphBackend):
    """Optional backend stub for future phases."""

    def add_node(self, node: GraphNode) -> None:
        raise NotImplementedError("Neo4j backend is not implemented in phase 1")

    def add_edge(self, edge: GraphEdge) -> None:
        raise NotImplementedError("Neo4j backend is not implemented in phase 1")

    def query_neighbors(self, node_id: str) -> list[str]:
        raise NotImplementedError("Neo4j backend is not implemented in phase 1")

    def has_node(self, node_id: str) -> bool:
        raise NotImplementedError("Neo4j backend is not implemented in phase 1")

    def has_edge(self, source: str, target: str) -> bool:
        raise NotImplementedError("Neo4j backend is not implemented in phase 1")

    def search_nodes(self, query: str, node_type: str | None = None, limit: int = 20) -> list[dict[str, str]]:
        raise NotImplementedError("Neo4j backend is not implemented in phase 1")

    def export_snapshot(self) -> dict[str, object]:
        raise NotImplementedError("Neo4j backend is not implemented in phase 1")

    def import_snapshot(self, snapshot: dict[str, object], *, clear_existing: bool = False) -> dict[str, int]:
        raise NotImplementedError("Neo4j backend is not implemented in phase 1")
