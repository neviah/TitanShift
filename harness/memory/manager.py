from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.memory.graph.base import GraphEdge, GraphNode
from harness.memory.graph.networkx_backend import NetworkXGraphBackend
from harness.memory.semantic_sqlite import SemanticSQLiteStore
from harness.runtime.config import ConfigManager


@dataclass(slots=True)
class MemoryManager:
    config: ConfigManager
    workspace_root: Path
    working_memory: dict[str, dict[str, Any]] = field(default_factory=dict)
    short_term: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    long_term: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    semantic: SemanticSQLiteStore = field(init=False)
    graph: NetworkXGraphBackend = field(init=False)

    def __post_init__(self) -> None:
        storage_root = self.workspace_root / self.config.get("memory.storage_dir", ".harness")
        storage_root.mkdir(parents=True, exist_ok=True)
        sqlite_name = self.config.get("memory.sqlite_file", "memory.db")
        self.semantic = SemanticSQLiteStore(storage_root / sqlite_name)
        self.graph = NetworkXGraphBackend()

    def save_fact(self, scope: str, fact: dict[str, Any]) -> None:
        self.long_term.setdefault(scope, []).append(fact)

    def query_facts(self, scope: str | None = None) -> list[dict[str, Any]]:
        if scope is None:
            all_facts: list[dict[str, Any]] = []
            for bucket in self.long_term.values():
                all_facts.extend(bucket)
            return all_facts
        return list(self.long_term.get(scope, []))

    def set_working(self, agent_id: str, key: str, value: Any) -> None:
        self.working_memory.setdefault(agent_id, {})[key] = value

    def get_working(self, agent_id: str, key: str) -> Any:
        return self.working_memory.get(agent_id, {}).get(key)

    def append_short_term(self, agent_id: str, entry: dict[str, Any]) -> None:
        self.short_term.setdefault(agent_id, []).append(entry)

    def embed_and_store(self, doc_id: str, text: str, metadata: dict[str, Any], embedding: list[float]) -> None:
        self.semantic.embed_and_store(doc_id=doc_id, text=text, metadata=metadata, embedding=embedding)

    def semantic_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.semantic.semantic_search(query=query, limit=limit)

    def graph_has_node(self, node_id: str) -> bool:
        return self.graph.has_node(node_id)

    def graph_has_edge(self, source: str, target: str) -> bool:
        return self.graph.has_edge(source, target)

    def graph_add_node(self, node_id: str, node_type: str, properties: dict[str, str] | None = None) -> None:
        self.graph.add_node(GraphNode(node_id=node_id, node_type=node_type, properties=properties or {}))

    def graph_add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        properties: dict[str, str] | None = None,
    ) -> None:
        self.graph.add_edge(
            GraphEdge(source=source, target=target, edge_type=edge_type, properties=properties or {})
        )

    def graph_neighbors(self, node_id: str) -> list[str]:
        return self.graph.query_neighbors(node_id)

    def graph_search_nodes(self, query: str, node_type: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return self.graph.search_nodes(query=query, node_type=node_type, limit=limit)

    def summary(self) -> dict[str, int]:
        working_agents = len(self.working_memory)
        working_entries = sum(len(v) for v in self.working_memory.values())
        short_term_agents = len(self.short_term)
        short_term_entries = sum(len(v) for v in self.short_term.values())
        long_term_scopes = len(self.long_term)
        long_term_entries = sum(len(v) for v in self.long_term.values())
        return {
            "working_agents": working_agents,
            "working_entries": working_entries,
            "short_term_agents": short_term_agents,
            "short_term_entries": short_term_entries,
            "long_term_scopes": long_term_scopes,
            "long_term_entries": long_term_entries,
        }
