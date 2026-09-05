from __future__ import annotations

import logging
from collections import deque
from typing import Any

import networkx as nx

from tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

IMPACT_DECAY = [1.0, 0.5, 0.25]  # depth 0, 1, 2

VISIBILITY_WEIGHT = {
    "public": 1.0,
    "protected": 0.6,
    "package-private": 0.3,
    "private": 0.0,  # private changes don't propagate
    "default": 0.5,
}


class CodeKnowledgeGraphTool(Tool):
    name = "code_knowledge_graph"

    def run(self, payload: dict, context: ToolContext | None = None) -> ToolResult:
        entities = payload.get("entities", [])
        relations = payload.get("relations", [])
        changed_files = payload.get("changed_files", [])

        graph = nx.DiGraph()

        for e in entities:
            qname = (
                e.get("fully_qualified_name")
                or f"{e.get('file_path','')}::{e.get('name','')}"
            )
            graph.add_node(
                qname,
                kind=e.get("kind", "unknown"),
                file=e.get("file_path", ""),
                line=e.get("line_start", 0),
                language=e.get("language", ""),
                modifiers=e.get("modifiers", []),
                signature=e.get("signature", ""),
            )

        for r in relations:
            graph.add_edge(
                r.get("source", ""),
                r.get("target", ""),
                relation=r.get("relation_type", "REFERENCES"),
            )

        impact = self._compute_decay_impact(graph, entities, changed_files)

        try:
            graph_data = nx.node_link_data(graph)
        except Exception:
            graph_data = {"nodes": [], "links": []}

        return ToolResult(
            name=self.name, payload={"graph_data": graph_data, "impact": impact}
        )

    def _compute_decay_impact(
        self, graph: nx.DiGraph, entities: list[dict], changed_files: list[str]
    ) -> dict[str, Any]:
        changed_nodes: list[str] = []
        for e in entities:
            if e.get("file_path", "") in changed_files:
                qname = (
                    e.get("fully_qualified_name")
                    or f"{e.get('file_path','')}::{e.get('name','')}"
                )
                changed_nodes.append(qname)

        if not changed_nodes or graph.number_of_nodes() == 0:
            return {
                "changed_files": changed_files,
                "affected": [],
                "total_impact_score": 0,
            }

        # Weighted BFS with decay
        affected: dict[str, float] = {}  # node -> impact_score
        for node in changed_nodes:
            if node not in graph:
                continue
            node_data = graph.nodes[node]
            visibility = self._get_visibility(
                node_data.get("modifiers", []), node_data.get("kind", "")
            )
            if visibility == 0:
                continue
            affected[node] = IMPACT_DECAY[0] * visibility

        queue: deque[tuple[str, int, float]] = deque()
        for node, score in list(affected.items()):
            for _, neighbor, edge_data in graph.out_edges(node, data=True):
                queue.append((neighbor, 1, score))

        while queue:
            node, depth, inherited_score = queue.popleft()
            if depth >= len(IMPACT_DECAY):
                continue
            if node not in graph:
                continue

            node_data = graph.nodes[node]
            visibility = self._get_visibility(
                node_data.get("modifiers", []), node_data.get("kind", "")
            )
            new_score = inherited_score * IMPACT_DECAY[depth] * visibility
            if new_score <= 0.01:
                continue

            if node not in affected or new_score > affected[node]:
                affected[node] = new_score

            if depth + 1 < len(IMPACT_DECAY):
                for _, neighbor, edge_data in graph.out_edges(node, data=True):
                    queue.append((neighbor, depth + 1, new_score))

        affected_sorted = sorted(affected.items(), key=lambda x: x[1], reverse=True)
        affected_files = list(
            {
                graph.nodes[n].get("file", "")
                for n, _ in affected_sorted
                if n in graph and graph.nodes[n].get("file")
            }
        )

        return {
            "changed_files": changed_files,
            "changed_nodes": changed_nodes,
            "affected": [{"node": n, "score": round(s, 3)} for n, s in affected_sorted],
            "affected_files": affected_files,
            "total_impact_score": round(sum(s for _, s in affected_sorted), 3),
        }

    def _get_visibility(self, modifiers: list[str], kind: str) -> float:
        if not modifiers:
            return VISIBILITY_WEIGHT.get("default", 0.5)
        for mod in modifiers:
            lower = mod.lower() if isinstance(mod, str) else ""
            if lower in VISIBILITY_WEIGHT:
                return VISIBILITY_WEIGHT[lower]
        # private methods/fields don't propagate
        if "private" in [m.lower() if isinstance(m, str) else "" for m in modifiers]:
            return 0
        return VISIBILITY_WEIGHT.get("default", 0.5)
