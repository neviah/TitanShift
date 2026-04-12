from __future__ import annotations

import re
from typing import Any

from harness.memory.graph.base import GraphBackend, GraphEdge, GraphNode


class Neo4jGraphBackend(GraphBackend):
    """Neo4j-backed graph implementation.

    Uses node_id as the stable identity across backends.
    """

    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str | None = None,
    ) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("neo4j package is required for Neo4jGraphBackend") from exc

        self._driver = GraphDatabase.driver(uri, auth=(username, password))
        self._database = database

    @staticmethod
    def _safe_token(value: str, *, fallback: str) -> str:
        token = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
        token = token.strip("_")
        return token or fallback

    def _run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        with self._driver.session(database=self._database) as session:
            result = session.run(query, **params)
            return [dict(r) for r in result]

    def close(self) -> None:
        self._driver.close()

    def add_node(self, node: GraphNode) -> None:
        label = self._safe_token(node.node_type, fallback="concept")
        q = (
            f"MERGE (n:`{label}` {{node_id: $node_id}}) "
            "SET n.node_type = $node_type "
            "SET n += $props"
        )
        props = {str(k): str(v) for k, v in node.properties.items()}
        self._run(q, node_id=node.node_id, node_type=node.node_type, props=props)

    def add_edge(self, edge: GraphEdge) -> None:
        rel = self._safe_token(edge.edge_type.upper(), fallback="RELATED_TO")
        q = (
            "MATCH (a {node_id: $source}), (b {node_id: $target}) "
            f"MERGE (a)-[r:`{rel}`]->(b) "
            "SET r.edge_type = $edge_type "
            "SET r += $props"
        )
        props = {str(k): str(v) for k, v in edge.properties.items()}
        self._run(
            q,
            source=edge.source,
            target=edge.target,
            edge_type=edge.edge_type,
            props=props,
        )

    def query_neighbors(self, node_id: str) -> list[str]:
        rows = self._run(
            "MATCH (s {node_id: $node_id})-[r]->(n) RETURN DISTINCT n.node_id AS node_id",
            node_id=node_id,
        )
        return [str(r.get("node_id", "")).strip() for r in rows if str(r.get("node_id", "")).strip()]

    def has_node(self, node_id: str) -> bool:
        rows = self._run("MATCH (n {node_id: $node_id}) RETURN count(n) AS c", node_id=node_id)
        return bool(rows and int(rows[0].get("c", 0)) > 0)

    def has_edge(self, source: str, target: str) -> bool:
        rows = self._run(
            "MATCH (a {node_id: $source})-[r]->(b {node_id: $target}) RETURN count(r) AS c",
            source=source,
            target=target,
        )
        return bool(rows and int(rows[0].get("c", 0)) > 0)

    def search_nodes(self, query: str, node_type: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        clamped_limit = max(1, limit)
        rows = self._run(
            "MATCH (n) RETURN n.node_id AS node_id, n.node_type AS node_type, properties(n) AS props "
            "LIMIT $limit",
            limit=clamped_limit * 5,
        )
        needle = query.lower().strip()
        out: list[dict[str, Any]] = []
        for row in rows:
            node_id = str(row.get("node_id", ""))
            current_type = str(row.get("node_type", ""))
            if node_type and current_type != node_type:
                continue
            props = dict(row.get("props", {}) or {})
            hay = [node_id.lower(), current_type.lower()] + [str(v).lower() for v in props.values()]
            if needle and not any(needle in h for h in hay):
                continue
            out.append(
                {
                    "node_id": node_id,
                    "node_type": current_type,
                    "properties": {
                        str(k): str(v)
                        for k, v in props.items()
                        if k not in {"node_id", "node_type"}
                    },
                }
            )
            if len(out) >= clamped_limit:
                break
        return out

    def export_snapshot(self) -> dict[str, Any]:
        node_rows = self._run("MATCH (n) RETURN n.node_id AS node_id, n.node_type AS node_type, properties(n) AS props")
        nodes: list[dict[str, Any]] = []
        for row in node_rows:
            node_id = str(row.get("node_id", "")).strip()
            if not node_id:
                continue
            node_type = str(row.get("node_type", "concept"))
            props = dict(row.get("props", {}) or {})
            nodes.append(
                {
                    "node_id": node_id,
                    "node_type": node_type,
                    "properties": {
                        str(k): str(v)
                        for k, v in props.items()
                        if k not in {"node_id", "node_type"}
                    },
                }
            )

        edge_rows = self._run(
            "MATCH (a)-[r]->(b) RETURN a.node_id AS source, b.node_id AS target, r.edge_type AS edge_type, properties(r) AS props"
        )
        edges: list[dict[str, Any]] = []
        for row in edge_rows:
            source = str(row.get("source", "")).strip()
            target = str(row.get("target", "")).strip()
            if not source or not target:
                continue
            edge_type = str(row.get("edge_type", "related_to"))
            props = dict(row.get("props", {}) or {})
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "edge_type": edge_type,
                    "properties": {
                        str(k): str(v)
                        for k, v in props.items()
                        if k != "edge_type"
                    },
                }
            )
        return {"nodes": nodes, "edges": edges}

    def import_snapshot(self, snapshot: dict[str, Any], *, clear_existing: bool = False) -> dict[str, int]:
        if clear_existing:
            self._run("MATCH (n) DETACH DELETE n")

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
            self.add_node(GraphNode(node_id=node_id, node_type=node_type, properties=safe_props))
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
            self.add_edge(GraphEdge(source=source, target=target, edge_type=edge_type, properties=safe_props))
            edges_added += 1

        return {"nodes_added": nodes_added, "edges_added": edges_added}
