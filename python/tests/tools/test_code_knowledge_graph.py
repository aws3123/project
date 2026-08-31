"""Tests for code knowledge graph with weighted decay impact analysis."""

from tools.code_knowledge_graph import CodeKnowledgeGraphTool


def test_kg_builds_graph_from_entities():
    tool = CodeKnowledgeGraphTool()
    entities = [
        {"name": "UserService", "kind": "class", "file_path": "UserService.java",
         "line_start": 10, "language": "java", "fully_qualified_name": "com.app.UserService",
         "modifiers": ["public"]},
        {"name": "getUserName", "kind": "method", "file_path": "UserService.java",
         "line_start": 15, "language": "java", "fully_qualified_name": "com.app.UserService::getUserName",
         "modifiers": ["public"]},
    ]
    relations = [
        {"source": "com.app.UserService::getUserName", "target": "com.app.UserService",
         "relation_type": "REFERENCES"},
    ]
    result = tool.run({
        "entities": entities, "relations": relations,
        "changed_files": ["UserService.java"],
    })
    assert result.payload["impact"]["total_impact_score"] >= 0


def test_kg_private_method_no_propagation():
    tool = CodeKnowledgeGraphTool()
    entities = [
        {"name": "Service", "kind": "class", "file_path": "Service.java",
         "line_start": 1, "language": "java", "fully_qualified_name": "com.Service",
         "modifiers": ["public"]},
        {"name": "privateHelper", "kind": "method", "file_path": "Service.java",
         "line_start": 10, "language": "java", "fully_qualified_name": "com.Service::privateHelper",
         "modifiers": ["private"]},
        {"name": "Controller", "kind": "class", "file_path": "Controller.java",
         "line_start": 1, "language": "java", "fully_qualified_name": "com.Controller",
         "modifiers": ["public"]},
    ]
    relations = [
        {"source": "com.Controller", "target": "com.Service::privateHelper", "relation_type": "CALLS"},
    ]
    result = tool.run({
        "entities": entities, "relations": relations,
        "changed_files": ["Service.java"],
    })
    affected_nodes = [a["node"] for a in result.payload["impact"]["affected"]]
    # private method should NOT propagate impact to Controller
    assert "com.Controller" not in affected_nodes or len(affected_nodes) <= 1


def test_kg_weighted_decay():
    tool = CodeKnowledgeGraphTool()
    entities = [
        {"name": "A", "kind": "class", "file_path": "A.java", "line_start": 1, "language": "java",
         "fully_qualified_name": "com.A", "modifiers": ["public"]},
        {"name": "B", "kind": "class", "file_path": "B.java", "line_start": 1, "language": "java",
         "fully_qualified_name": "com.B", "modifiers": ["public"]},
        {"name": "C", "kind": "class", "file_path": "C.java", "line_start": 1, "language": "java",
         "fully_qualified_name": "com.C", "modifiers": ["public"]},
    ]
    relations = [
        {"source": "com.A", "target": "com.B", "relation_type": "CALLS"},
        {"source": "com.B", "target": "com.C", "relation_type": "CALLS"},
    ]
    result = tool.run({
        "entities": entities, "relations": relations,
        "changed_files": ["A.java"],
    })
    affected = {a["node"]: a["score"] for a in result.payload["impact"]["affected"]}
    # A: depth 0 -> 1.0, B: depth 1 -> 0.5, C: depth 2 -> 0.25
    assert affected.get("com.A", 0) > affected.get("com.B", 0) > affected.get("com.C", 0)


def test_kg_empty_inputs():
    tool = CodeKnowledgeGraphTool()
    result = tool.run({"entities": [], "relations": [], "changed_files": []})
    assert result.payload["impact"]["total_impact_score"] == 0
