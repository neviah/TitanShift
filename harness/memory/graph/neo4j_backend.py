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
