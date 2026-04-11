from __future__ import annotations

from typing import Any

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

    def has_node(self, node_id: str) -> bool:
        return bool(self._graph.has_node(node_id))

    def has_edge(self, source: str, target: str) -> bool:
        return bool(self._graph.has_edge(source, target))

    def query_neighbors(self, node_id: str) -> list[str]:
        if node_id not in self._graph:
            return []
        return list(self._graph.neighbors(node_id))

    def search_nodes(self, query: str, node_type: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        needle = query.lower().strip()
        out: list[dict[str, Any]] = []
        for node_id, attrs in self._graph.nodes(data=True):
            current_type = str(attrs.get("node_type", ""))
            if node_type and current_type != node_type:
                continue

            haystacks = [str(node_id).lower(), current_type.lower()]
            haystacks.extend(str(v).lower() for v in attrs.values())
            if needle and not any(needle in h for h in haystacks):
                continue

            out.append(
                {
                    "node_id": str(node_id),
                    "node_type": current_type,
                    "properties": {k: str(v) for k, v in attrs.items() if k != "node_type"},
                }
            )
            if len(out) >= max(1, limit):
                break
        return out
