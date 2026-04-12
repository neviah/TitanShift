from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _safe_cypher_token(value: str, *, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
    token = token.strip("_")
    return token or fallback


def read_snapshot(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Graph snapshot must be a JSON object")
    nodes = loaded.get("nodes", [])
    edges = loaded.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Graph snapshot requires list fields: nodes and edges")
    return {"nodes": nodes, "edges": edges}


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "nodes": list(snapshot.get("nodes", [])),
        "edges": list(snapshot.get("edges", [])),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def export_from_neo4j(
    *,
    uri: str,
    username: str,
    password: str,
    database: str | None = None,
) -> dict[str, Any]:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("Neo4j export requires neo4j Python package") from exc

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            node_rows = session.run(
                "MATCH (n) RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS props"
            )
            node_map: dict[str, str] = {}
            nodes: list[dict[str, Any]] = []
            for row in node_rows:
                element_id = str(row["element_id"])
                props = dict(row["props"] or {})
                raw_id = str(props.get("node_id", "")).strip()
                node_id = raw_id or f"neo4j:{element_id}"
                labels = [str(v) for v in (row["labels"] or [])]
                inferred_type = str(props.get("node_type", "")).strip() or (labels[0].lower() if labels else "concept")
                exported_props = {str(k): str(v) for k, v in props.items() if k not in {"node_id", "node_type"}}
                nodes.append({"node_id": node_id, "node_type": inferred_type, "properties": exported_props})
                node_map[element_id] = node_id

            edge_rows = session.run(
                "MATCH (a)-[r]->(b) RETURN elementId(a) AS src_id, elementId(b) AS tgt_id, type(r) AS rel_type, properties(r) AS props"
            )
            edges: list[dict[str, Any]] = []
            for row in edge_rows:
                src_node = node_map.get(str(row["src_id"]))
                tgt_node = node_map.get(str(row["tgt_id"]))
                if not src_node or not tgt_node:
                    continue
                props = dict(row["props"] or {})
                edge_type = str(props.get("edge_type", "")).strip() or str(row["rel_type"] or "related_to").lower()
                exported_props = {str(k): str(v) for k, v in props.items() if k != "edge_type"}
                edges.append({"source": src_node, "target": tgt_node, "edge_type": edge_type, "properties": exported_props})

            return {"nodes": nodes, "edges": edges}
    finally:
        driver.close()


def import_to_neo4j(
    *,
    snapshot: dict[str, Any],
    uri: str,
    username: str,
    password: str,
    database: str | None = None,
    clear_existing: bool = False,
) -> dict[str, int]:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("Neo4j import requires neo4j Python package") from exc

    driver = GraphDatabase.driver(uri, auth=(username, password))
    nodes_added = 0
    edges_added = 0
    try:
        with driver.session(database=database) as session:
            if clear_existing:
                session.run("MATCH (n) DETACH DELETE n")

            for node in list(snapshot.get("nodes", [])):
                if not isinstance(node, dict):
                    continue
                node_id = str(node.get("node_id", "")).strip()
                if not node_id:
                    continue
                node_type = str(node.get("node_type", "concept")).strip() or "concept"
                label = _safe_cypher_token(node_type, fallback="concept")
                props = node.get("properties", {})
                safe_props = {str(k): str(v) for k, v in dict(props).items()} if isinstance(props, dict) else {}
                query = (
                    f"MERGE (n:`{label}` {{node_id: $node_id}}) "
                    "SET n.node_type = $node_type "
                    "SET n += $props"
                )
                session.run(query, node_id=node_id, node_type=node_type, props=safe_props)
                nodes_added += 1

            for edge in list(snapshot.get("edges", [])):
                if not isinstance(edge, dict):
                    continue
                source = str(edge.get("source", "")).strip()
                target = str(edge.get("target", "")).strip()
                if not source or not target:
                    continue
                edge_type = str(edge.get("edge_type", "related_to")).strip() or "related_to"
                rel_type = _safe_cypher_token(edge_type.upper(), fallback="RELATED_TO")
                props = edge.get("properties", {})
                safe_props = {str(k): str(v) for k, v in dict(props).items()} if isinstance(props, dict) else {}
                query = (
                    "MATCH (a {node_id: $source_id}), (b {node_id: $target_id}) "
                    f"MERGE (a)-[r:`{rel_type}`]->(b) "
                    "SET r.edge_type = $edge_type "
                    "SET r += $props"
                )
                result = session.run(
                    query,
                    source_id=source,
                    target_id=target,
                    edge_type=edge_type,
                    props=safe_props,
                )
                _ = result.consume()
                edges_added += 1

        return {"nodes_added": nodes_added, "edges_added": edges_added}
    finally:
        driver.close()
