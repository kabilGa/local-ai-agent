from __future__ import annotations

import json
import logging
from typing import List

import networkx as nx

logger = logging.getLogger(__name__)


class SymbolGraph:
    """
    Directed graph of symbol relationships (calls, imports).
    Answers queries like:
      - "All callers of authenticate_user up to depth 2"
      - "What does parse_token call?"

    Persisted as JSON in Redis (key: symbol_graph:{project_id}).
    TTL default: 24 h — refreshed on each re-indexation.
    """

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()

    # ── Graph construction ────────────────────────────────────────────────────

    def add_call_edge(self, caller_fqn: str, callee_fqn: str) -> None:
        """caller → callee: caller calls callee."""
        self.graph.add_edge(caller_fqn, callee_fqn, relation="calls")

    def add_import_edge(self, importer_fqn: str, imported_symbol: str) -> None:
        """importer → imported_symbol."""
        self.graph.add_edge(importer_fqn, imported_symbol, relation="imports")

    def update_called_by(self) -> None:
        """
        Invert call edges to populate called_by on each node.
        Call after all add_call_edge() calls are complete.
        """
        for node in self.graph.nodes:
            callers = list(nx.ancestors(self.graph, node))
            self.graph.nodes[node]["called_by"] = callers

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_callers(self, fqn: str, depth: int = 2) -> List[str]:
        """Return FQNs that call `fqn`, up to `depth` hops."""
        try:
            callers = nx.ancestors(self.graph, fqn)
            # Filter by depth using BFS
            if depth < 99:
                callers = set()
                queue = [(fqn, 0)]
                visited = {fqn}
                while queue:
                    node, d = queue.pop(0)
                    if d >= depth:
                        continue
                    for pred in self.graph.predecessors(node):
                        if pred not in visited:
                            visited.add(pred)
                            callers.add(pred)
                            queue.append((pred, d + 1))
            return list(callers)
        except nx.NetworkXError:
            return []

    def get_callees(self, fqn: str) -> List[str]:
        """Return FQNs called by `fqn`."""
        try:
            return list(self.graph.successors(fqn))
        except nx.NetworkXError:
            return []

    def get_dependency_context(self, fqn: str) -> dict:
        return {
            "fqn": fqn,
            "calls": self.get_callees(fqn),
            "called_by": self.get_callers(fqn, depth=2),
            "importance_score": self.graph.in_degree(fqn) if fqn in self.graph else 0,
        }

    def search_by_name(self, name: str) -> List[str]:
        """Find nodes whose FQN contains the given identifier name."""
        return [n for n in self.graph.nodes if name in n.split("::")[-1]]

    # ── Persistence ───────────────────────────────────────────────────────────

    def persist_to_redis(self, redis_client, project_id: str, ttl: int = 86400) -> None:
        try:
            data = nx.node_link_data(self.graph)
            redis_client.set(
                f"symbol_graph:{project_id}",
                json.dumps(data),
                ex=ttl,
            )
            logger.info("[graph] Persisted %d nodes for project %s", len(self.graph), project_id)
        except Exception as exc:
            logger.error("[graph] Redis persist failed: %s", exc)

    @classmethod
    def load_from_redis(cls, redis_client, project_id: str) -> "SymbolGraph | None":
        try:
            raw = redis_client.get(f"symbol_graph:{project_id}")
            if raw is None:
                return None
            g = cls()
            g.graph = nx.node_link_graph(json.loads(raw))
            return g
        except Exception as exc:
            logger.warning("[graph] Redis load failed for %s: %s", project_id, exc)
            return None

    def to_dict(self) -> dict:
        return nx.node_link_data(self.graph)

    @classmethod
    def from_dict(cls, data: dict) -> "SymbolGraph":
        g = cls()
        g.graph = nx.node_link_graph(data)
        return g

    def __len__(self) -> int:
        return len(self.graph)
