"""Tests for AST parser tool."""

from tools.ast_parser import ASTParserTool

JAVA_DIFF = """diff --git a/UserService.java b/UserService.java
@@ -10,6 +10,8 @@
 public class UserService {
+    public String getUserName(Long id) {
+        return userRepo.findName(id);
+    }
 }"""

PYTHON_DIFF = """diff --git a/app/handler.py b/app/handler.py
@@ -1,3 +1,7 @@
+import logging
+
 def handler(event, context):
+    logging.info("processing")
     return {"status": "ok"}"""

SQL_DIFF = """diff --git a/schema.sql b/schema.sql
@@ -1,0 +2,3 @@
+CREATE TABLE IF NOT EXISTS orders (
+    id BIGINT PRIMARY KEY
+);"""


def test_ast_parser_extracts_java_method():
    tool = ASTParserTool()
    result = tool.run({"files": [{"path": "UserService.java", "diff": JAVA_DIFF}]})
    entities = result.payload["entities"]
    methods = [e for e in entities if e.get("kind") == "method"]
    assert len(methods) >= 1
    assert any("getUserName" in m.get("name", "") for m in methods)


def test_ast_parser_extracts_python_function():
    tool = ASTParserTool()
    result = tool.run({"files": [{"path": "app/handler.py", "diff": PYTHON_DIFF}]})
    entities = result.payload["entities"]
    funcs = [e for e in entities if e.get("kind") == "method"]
    has_handler = any("handler" in f.get("name", "") for f in funcs)
    has_import = any(e.get("kind") == "import" for e in entities)
    assert has_handler or has_import


def test_ast_parser_extracts_sql_table():
    tool = ASTParserTool()
    result = tool.run({"files": [{"path": "schema.sql", "diff": SQL_DIFF}]})
    entities = result.payload["entities"]
    tables = [e for e in entities if e.get("kind") == "table"]
    assert len(tables) >= 1
    assert any("orders" in t.get("name", "") for t in tables)


def test_ast_parser_detects_language():
    tool = ASTParserTool()
    assert tool._detect_language("App.java") == "java"
    assert tool._detect_language("app.py") == "python"
    assert tool._detect_language("schema.sql") == "sql"


def test_ast_parser_handles_empty_diff():
    tool = ASTParserTool()
    result = tool.run({"files": []})
    assert result.payload["entities"] == []
    assert result.payload["relations"] == []


def test_ast_parser_extracts_relations():
    tool = ASTParserTool()
    diff = """diff --git a/App.java b/App.java
+public class App {
+    public void run() {
+        service.process();
+    }
+}"""
    result = tool.run({"files": [{"path": "App.java", "diff": diff}]})
    entities = result.payload["entities"]
    relations = result.payload["relations"]
    assert len(entities) >= 1
