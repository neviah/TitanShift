from __future__ import annotations

from harness.memory.graph.base import GraphBackend, GraphEdge, GraphNode

try:
    import networkx as nx
except ImportError:  # pragma: no cover
    nx = None


class NetworkXGraphBackend(GraphBackend):
    """Default graph backend for MVP: pure Python and portable."""

    def __init__(self) -> None:
        if nx is None:
            raise RuntimeError("networkx is required for NetworkXGraphBackend")
        self._graph = nx.MultiDiGraph()

    def add_node(self, node: GraphNode) -> None:
        self._graph.add_node(node.node_id, node_type=node.node_type, **node.properties)

    def add_edge(self, edge: GraphEdge) -> None:
        self._graph.add_edge(edge.source, edge.target, edge_type=edge.edge_type, **edge.properties)

    def query_neighbors(self, node_id: str) -> list[str]:
        if node_id not in self._graph:
            return []
        return list(self._graph.neighbors(node_id))
