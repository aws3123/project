from __future__ import annotations

from graph.nodes import rag as rag_module
from graph.state import NodeContext


class _Registry:
    def run(self, name, payload, context):
        assert name == "incident_search"
        return type(
            "Result",
            (),
            {
                "payload": {
                    "status": "NORMAL",
                    "reason": None,
                    "findings": [
                        {
                            "source": "incident-review-001",
                            "topic": "incident-a",
                            "snippet": "cache invalidation",
                            "score": 0.9,
                            "citation": {
                                "source": "incident-review-001",
                                "title": "incident-a",
                                "snippet": "cache invalidation",
                            },
                        }
                    ],
                }
            },
        )()


def test_run_rag_keeps_rag_context_shape_with_local_keyword_search(monkeypatch):
    monkeypatch.setattr(
        rag_module,
        "AppSettings",
        lambda: type(
            "Settings",
            (),
            {"top_k": 2, "rrf_k": 60, "rag_max_tokens": 2000},
        )(),
    )
    monkeypatch.setattr(
        rag_module,
        "search_incidents_keyword_local",
        lambda query, top_k, settings=None: [
            {
                "title": "incident-b",
                "snippet": "transaction boundary",
                "source": "keyword-source",
                "service": "svc",
                "tags": ["tx"],
                "score": 0.5,
            }
        ],
    )

    state = {
        "task_id": "t-1",
        "request": {"metadata": {}},
        "classification": {"layers": ["service"]},
        "diff_analysis": {
            "summary": {"paths": ["service/UserService.java"]},
            "files": [],
        },
        "code_graph": {},
        "impact_radius": {},
    }
    ctx = NodeContext(task_id="t-1", registry=_Registry(), llm_client=None)

    result = rag_module.run_rag(state, ctx)

    assert result["rag_status"] == "NORMAL"
    assert result["tool_logs"][0]["method"] == "vector+bm25+rrf"
    assert result["rag_context"][0]["topic"] == "incident-a"


class _EmptyRegistry:
    def run(self, name, payload, context):
        assert name == "incident_search"
        return type(
            "Result",
            (),
            {
                "payload": {
                    "status": "NORMAL",
                    "reason": None,
                    "findings": [],
                }
            },
        )()


def test_run_rag_keeps_empty_context_when_all_retrievals_are_empty(monkeypatch):
    monkeypatch.setattr(
        rag_module,
        "AppSettings",
        lambda: type(
            "Settings",
            (),
            {"top_k": 2, "rrf_k": 60, "rag_max_tokens": 2000},
        )(),
    )
    monkeypatch.setattr(
        rag_module,
        "search_incidents_keyword_local",
        lambda query, top_k, settings=None: [],
    )

    state = {
        "task_id": "t-2",
        "request": {"metadata": {}},
        "classification": {"layers": ["service"]},
        "diff_analysis": {"summary": {"paths": []}, "files": []},
        "code_graph": {},
        "impact_radius": {},
    }
    ctx = NodeContext(task_id="t-2", registry=_EmptyRegistry(), llm_client=None)

    result = rag_module.run_rag(state, ctx)

    assert result["rag_status"] == "NORMAL"
    assert result["rag_context"] == []
    assert result["tool_logs"][0]["findings"] == []
    assert result["tool_logs"][0]["method"] == "vector+rrf"


def test_run_rag_filters_zero_score_keyword_rows(monkeypatch):
    monkeypatch.setattr(
        rag_module,
        "AppSettings",
        lambda: type(
            "Settings",
            (),
            {"top_k": 2, "rrf_k": 60, "rag_max_tokens": 2000},
        )(),
    )
    monkeypatch.setattr(
        rag_module,
        "search_incidents_keyword_local",
        lambda query, top_k, settings=None: [
            {
                "title": "incident-zero",
                "snippet": "irrelevant",
                "source": "keyword-source",
                "service": "svc",
                "tags": [],
                "score": 0.0,
            }
        ],
    )

    state = {
        "task_id": "t-3",
        "request": {"metadata": {}},
        "classification": {"layers": ["service"]},
        "diff_analysis": {"summary": {"paths": []}, "files": []},
        "code_graph": {},
        "impact_radius": {},
    }
    ctx = NodeContext(task_id="t-3", registry=_EmptyRegistry(), llm_client=None)

    result = rag_module.run_rag(state, ctx)

    assert result["rag_context"] == []
    assert result["tool_logs"][0]["method"] == "vector+rrf"


def test_run_rag_fuses_same_incident_across_vector_and_keyword(monkeypatch):
    monkeypatch.setattr(
        rag_module,
        "AppSettings",
        lambda: type(
            "Settings",
            (),
            {"top_k": 2, "rrf_k": 60, "rag_max_tokens": 2000},
        )(),
    )
    monkeypatch.setattr(
        rag_module,
        "search_incidents_keyword_local",
        lambda query, top_k, settings=None: [
            {
                "title": "incident-a",
                "snippet": "cache invalidation",
                "source": "incident-review-001",
                "service": "svc",
                "tags": ["cache"],
                "score": 0.5,
            }
        ],
    )

    state = {
        "task_id": "t-4",
        "request": {"metadata": {}},
        "classification": {"layers": ["service"]},
        "diff_analysis": {"summary": {"paths": []}, "files": []},
        "code_graph": {},
        "impact_radius": {},
    }
    ctx = NodeContext(task_id="t-4", registry=_Registry(), llm_client=None)

    result = rag_module.run_rag(state, ctx)

    assert len(result["rag_context"]) == 1
    assert result["rag_context"][0]["topic"] == "incident-a"
    assert result["tool_logs"][0]["method"] == "vector+bm25+rrf"
