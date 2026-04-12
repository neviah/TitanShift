from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.memory.graph.base import GraphBackend, GraphEdge, GraphNode

try:
    import networkx as nx
except ImportError:  # pragma: no cover
    nx = None


class NetworkXGraphBackend(GraphBackend):
    """Default graph backend for MVP: pure Python and portable."""

    def __init__(self, persistence_path: Path | None = None) -> None:
        if nx is None:
            raise RuntimeError("networkx is required for NetworkXGraphBackend")
        self._graph = nx.MultiDiGraph()
        self._persistence_path = persistence_path
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        try:
            payload = json.loads(self._persistence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
        edges = payload.get("edges", []) if isinstance(payload, dict) else []

        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_id = str(node.get("node_id", "")).strip()
                if not node_id:
                    continue
                node_type = str(node.get("node_type", "concept"))
                properties = node.get("properties", {})
                safe_props = (
                    {str(k): str(v) for k, v in properties.items()}
                    if isinstance(properties, dict)
                    else {}
                )
                self._graph.add_node(node_id, node_type=node_type, **safe_props)

        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                source = str(edge.get("source", "")).strip()
                target = str(edge.get("target", "")).strip()
                if not source or not target:
                    continue
                edge_type = str(edge.get("edge_type", "related_to"))
                properties = edge.get("properties", {})
                safe_props = (
                    {str(k): str(v) for k, v in properties.items()}
                    if isinstance(properties, dict)
                    else {}
                )
                self._graph.add_edge(source, target, edge_type=edge_type, **safe_props)

    def _persist_to_disk(self) -> None:
        if self._persistence_path is None:
            return
        payload = self.export_snapshot()
        self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._persistence_path.with_suffix(self._persistence_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self._persistence_path)

    def add_node(self, node: GraphNode) -> None:
        self._graph.add_node(node.node_id, node_type=node.node_type, **node.properties)
        self._persist_to_disk()

    def add_edge(self, edge: GraphEdge) -> None:
        self._graph.add_edge(edge.source, edge.target, edge_type=edge.edge_type, **edge.properties)
        self._persist_to_disk()

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

    def export_snapshot(self) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        for node_id, attrs in self._graph.nodes(data=True):
            nodes.append(
                {
                    "node_id": str(node_id),
                    "node_type": str(attrs.get("node_type", "")),
                    "properties": {k: str(v) for k, v in attrs.items() if k != "node_type"},
                }
            )

        edges: list[dict[str, Any]] = []
        for source, target, attrs in self._graph.edges(data=True):
            edges.append(
                {
                    "source": str(source),
                    "target": str(target),
                    "edge_type": str(attrs.get("edge_type", "")),
                    "properties": {k: str(v) for k, v in attrs.items() if k != "edge_type"},
                }
            )
        return {"nodes": nodes, "edges": edges}

    def import_snapshot(self, snapshot: dict[str, Any], *, clear_existing: bool = False) -> dict[str, int]:
        if clear_existing:
            self._graph.clear()

        nodes_added = 0
        edges_added = 0

        for node in list(snapshot.get("nodes", [])):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id", "")).strip()
            if not node_id:
                continue
            node_type = str(node.get("node_type", "concept"))
            properties = node.get("properties", {})
            safe_props = {str(k): str(v) for k, v in dict(properties).items()} if isinstance(properties, dict) else {}
            existed = self._graph.has_node(node_id)
            self._graph.add_node(node_id, node_type=node_type, **safe_props)
            if not existed:
                nodes_added += 1

        for edge in list(snapshot.get("edges", [])):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if not source or not target:
                continue
            edge_type = str(edge.get("edge_type", "related_to"))
            properties = edge.get("properties", {})
            safe_props = {str(k): str(v) for k, v in dict(properties).items()} if isinstance(properties, dict) else {}
            existed = self._graph.has_edge(source, target)
            self._graph.add_edge(source, target, edge_type=edge_type, **safe_props)
            if not existed:
                edges_added += 1

        self._persist_to_disk()
        return {"nodes_added": nodes_added, "edges_added": edges_added}
