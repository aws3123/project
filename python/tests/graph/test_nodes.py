"""Unit tests for graph nodes — including security, performance, and cross-validation."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

from graph.nodes import (
    classifier,
    diff,
    impact,
    performance,
    rag,
    report,
    rules,
    scoring,
    security,
)
from graph.state import GraphState, NodeContext
from schemas.domain.llm_output import RAGAnalysisOutput, ReportOutput, ScoringOutput
from tools.base import ToolResult


def make_state(**overrides) -> GraphState:
    base: GraphState = {
        "task_id": "task-1",
        "request": {"files": [{"path": "app/controller.py", "diff": ""}]},
    }
    base.update(overrides)
    return base


# RAG 检索服务由依赖注入层创建；单元测试注入 fake，避免依赖 ES/embedding 基础设施。
def make_rag_retrieval_service(results=None, raise_exc: bool = False):
    if raise_exc:
        class _FakeRetrieval:
            async def retrieve(self, *args, **kwargs):
                raise RuntimeError(
                    "db down api_key=super-secret-token"  # 含敏感串，测试脱敏
                )

        return _FakeRetrieval()

    _DEFAULT = results or [
        {
            "title": "cache-db",
            "snippet": "双写不一致事故",
            "source": "kb",
            "score": 0.9,
        }
    ]

    class _FakeRetrieval:
        async def retrieve(self, *args, **kwargs):
            if results is not None:
                return [], "NORMAL", "no results"
            return _DEFAULT, "NORMAL", None

    return _FakeRetrieval()


def make_context(
    mock_registry=None, llm_client=None, rag_retrieval_service=None
) -> NodeContext:
    registry = mock_registry or Mock()
    if mock_registry is None:
        registry.run.return_value = ToolResult(name="tool", payload={"findings": []})
    return NodeContext(
        task_id="task-1",
        registry=registry,
        llm_client=llm_client,
        rag_retrieval_service=rag_retrieval_service,
    )


def make_llm_client(
    rag_analysis="", scoring_output=None, report_output=None
) -> MagicMock:
    llm = MagicMock()

    async def _chat_structured(messages=None, output_schema=None, **kwargs):
        if output_schema is RAGAnalysisOutput:
            return {
                "risk_association": rag_analysis,
                "related_incidents": [],
                "suggested_actions": [],
            }
        if output_schema is ScoringOutput:
            return scoring_output or {
                "risk_score": 65,
                "breakdown": [{"dimension": "安全", "score": 70, "reason": "SQL变更"}],
                "need_human_review": False,
                "risk_summary": "中等风险",
            }
        if output_schema is ReportOutput:
            return report_output or {
                "summary": "整体风险中等",
                "details": ["发现SQL变更"],
                "recommendations": [{"title": "建议1", "detail": "检查SQL"}],
            }
        return {}

    async def _chat(messages=None, **kwargs):
        return '{"findings": []}'

    llm.chat_structured = _chat_structured
    llm.chat = _chat
    return llm


# ---- diff ----


async def test_diff_node_stores_analysis():
    state = make_state()
    registry = Mock()
    registry.run.return_value = ToolResult(
        name="diff",
        payload={"files": state["request"]["files"], "summary": {"total_files": 1}},
    )
    ctx = make_context(registry)
    await diff.analyze_diff(state, ctx)
    assert "diff_analysis" in state


# ---- classifier ----


async def test_classifier_layers_generated():
    state = make_state()
    registry = Mock()
    registry.run.return_value = ToolResult(name="coverage", payload={"coverage": 0.5})
    ctx = make_context(registry)
    await classifier.classify_changes(state, ctx)
    assert state["classification"]["layers"] == ["controller"]


# ---- rules ----


async def test_rules_node_accumulates_findings():
    state = make_state(diff_analysis={"files": []}, request={})
    registry = Mock()
    registry.run.return_value = ToolResult(
        name="checker", payload={"findings": [{"severity": "HIGH"}]}
    )
    ctx = make_context(registry)
    await rules.run_rule_checks(state, ctx)
    assert state["rule_findings"][0]["tool"]


# ---- rag ----


async def test_rag_node_sets_context():
    state = make_state(
        classification={"layers": ["controller"]},
        request={"metadata": {}},
        diff_analysis={"summary": {"paths": []}},
    )
    retrieval_service = make_rag_retrieval_service()
    llm = make_llm_client(rag_analysis="存在SQL注入风险")
    ctx = make_context(llm_client=llm, rag_retrieval_service=retrieval_service)
    await rag.run_rag(state, ctx)
    assert state["rag_context"]
    assert "rag_analysis" in state


async def test_rag_node_with_graph_recall():
    state = make_state(
        classification={"layers": ["controller"]},
        request={"metadata": {}},
        diff_analysis={"summary": {"paths": ["App.java"]}},
        code_graph={
            "nodes": [
                {
                    "id": "com.App::run",
                    "kind": "method",
                    "file": "App.java",
                    "language": "java",
                },
            ],
            "links": [],
        },
        impact_radius={
            "changed_nodes": ["com.App::run"],
            "affected": [
                {"node": "com.App::run", "score": 1.0},
            ],
            "changed_files": ["App.java"],
            "affected_files": [],
        },
    )
    retrieval_service = make_rag_retrieval_service()
    ctx = make_context(llm_client=None, rag_retrieval_service=retrieval_service)
    await rag.run_rag(state, ctx)
    assert state["rag_context"]


async def test_rag_node_marks_degraded_when_incident_search_degrades():
    state = make_state(
        classification={"layers": ["controller"]},
        request={"metadata": {}},
        diff_analysis={"summary": {"paths": []}},
    )
    # 检索抛异常 → 节点应标记 DEGRADED 且不外泄内部错误串
    retrieval_service = make_rag_retrieval_service(raise_exc=True)
    ctx = make_context(llm_client=None, rag_retrieval_service=retrieval_service)
    await rag.run_rag(state, ctx)
    assert state["tool_logs"][-1]["status"] == "DEGRADED"
    assert state["rag_status"] == "DEGRADED"
    assert "super-secret-token" not in state["tool_logs"][-1]["reason"]


# ---- security ----


async def test_security_agent_deterministic_finds_hardcoded_password():
    state = make_state(
        diff_analysis={
            "files": [
                {
                    "path": "app/config.py",
                    "diff": '+password = "hardcoded123"\n-something else',
                }
            ]
        }
    )
    ctx = make_context(llm_client=None)
    await security.audit_security(state, ctx)
    assert len(state["security_findings"]) >= 1
    assert any("硬编码密码" in f["title"] for f in state["security_findings"])


async def test_security_agent_with_llm():
    state = make_state(
        diff_analysis={
            "files": [
                {
                    "path": "app/auth.py",
                    "diff": '+password = "secret123"\n+api_key = "sk-abc"',
                }
            ]
        }
    )
    llm = MagicMock()

    async def _chat(messages=None, **kwargs):
        return '{"findings": [{"severity":"HIGH","category":"security","title":"硬编码凭证","detail":"检测到硬编码","file":"app/auth.py","line":1,"suggestion":"移入环境变量","confidence":0.9}]}'

    llm.chat = _chat
    ctx = make_context(llm_client=llm)
    await security.audit_security(state, ctx)
    assert len(state["security_findings"]) >= 1


# ---- performance ----


async def test_performance_agent_deterministic_finds_n1_query():
    state = make_state(
        diff_analysis={
            "files": [
                {
                    "path": "app/service.py",
                    "diff": "+    for user in users:\n+        orders = orderRepo.find(user.id)",
                }
            ]
        }
    )
    ctx = make_context(llm_client=None)
    await performance.analyze_performance(state, ctx)
    assert len(state["performance_findings"]) >= 1
    assert any(
        "N+1" in f.get("title", "") or "循环" in f.get("title", "")
        for f in state["performance_findings"]
    )


async def test_performance_agent_with_llm():
    state = make_state(
        diff_analysis={
            "files": [
                {
                    "path": "app/repo.py",
                    "diff": '+    result = db.query("SELECT * FROM users")',
                }
            ]
        }
    )
    llm = MagicMock()

    async def _chat(messages=None, **kwargs):
        return '{"findings": [{"severity":"MEDIUM","category":"performance","title":"SELECT * 全表查询","detail":"未指定列","file":"app/repo.py","line":1,"suggestion":"指定需要列","confidence":0.8}]}'

    llm.chat = _chat
    ctx = make_context(llm_client=llm)
    await performance.analyze_performance(state, ctx)
    assert len(state["performance_findings"]) >= 1


# ---- impact ----


async def test_impact_node_parses_and_builds_graph():
    state = make_state(
        diff_analysis={
            "files": [
                {
                    "path": "app/handler.py",
                    "diff": "+\ndef handler(event, context):\n+    return {}",
                }
            ],
            "summary": {"paths": ["app/handler.py"]},
        }
    )
    registry = Mock()
    registry.run.return_value = ToolResult(
        name="tool",
        payload={
            "entities": [],
            "relations": [],
            "impact": {"changed_files": [], "affected": [], "total_impact_score": 0},
        },
    )
    ctx = make_context(registry)
    await impact.analyze_impact(state, ctx)
    assert "code_graph" in state
    assert "impact_radius" in state


# ---- scoring with cross-validation ----


async def test_scoring_cross_validation_detects_contradiction():
    state = make_state(
        rule_findings=[
            {
                "severity": "HIGH",
                "title": "SQL注入",
                "file": "a.sql",
                "line": 1,
                "confidence": 0.9,
            }
        ],
        security_findings=[
            {
                "severity": "LOW",
                "title": "无安全风险",
                "file": "a.sql",
                "line": 1,
                "confidence": 0.5,
            }
        ],
        performance_findings=[],
        rag_context=[{"source": "kb"}],
        classification={"summary": {"coverage": 1.0}},
    )
    ctx = make_context(llm_client=None)
    await scoring.score_risks(state, ctx)
    assert state["need_human_review"] is True


async def test_scoring_fallback_no_llm():
    state = make_state(
        rule_findings=[{"severity": "HIGH", "title": "SQL风险"}],
        security_findings=[],
        performance_findings=[],
        rag_context=[{"source": "kb"}],
        classification={"summary": {"coverage": 0.5}},
    )
    ctx = make_context(llm_client=None)
    await scoring.score_risks(state, ctx)
    assert state["risk_score"] >= 0.2
    assert len(state["breakdown"]) >= 3


# ---- report ----


async def test_report_llm_generates_recommendations():
    state = make_state(
        risk_score=0.65,
        risk_summary="中等风险",
        classification={"layers": ["controller"], "summary": {"coverage": 0.6}},
        rule_findings=[
            {
                "severity": "HIGH",
                "title": "SQL",
                "detail": "DELETE",
                "suggestion": "加WHERE",
            }
        ],
        security_findings=[],
        performance_findings=[],
        breakdown=[{"dimension": "安全", "score": 70, "reason": "SQL变更"}],
        rag_analysis="历史SQL事故相关",
    )
    llm = make_llm_client()
    ctx = make_context(llm_client=llm)
    await report.summarize(state, ctx)
    assert "整体风险" in state["summary"]
    assert len(state["recommendations"]) >= 1


async def test_report_fallback_no_llm():
    state = make_state(
        risk_score=0.7,
        classification={"layers": ["controller"], "summary": {"coverage": 0.6}},
        rule_findings=[{}],
    )
    ctx = make_context(llm_client=None)
    await report.summarize(state, ctx)
    assert state["summary"].startswith("整体风险")
    assert len(state["recommendations"]) == 2
