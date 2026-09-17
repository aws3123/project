from __future__ import annotations

from services.ast_query_builder import build_ast_retrieval_query


def test_ast_query_contains_identifiers_and_bilingual_risk_concepts():
    state = {
        "classification": {"layers": ["service"]},
        "diff_analysis": {
            "summary": {"paths": ["src/main/java/com/acme/OrderService.java"]},
            "files": [{"content": "@Transactional paymentClient.refund()"}],
        },
        "request": {
            "entities": [
                {"name": "OrderService.refund", "signature": "refund(Long id)"}
            ]
        },
        "source_package": {
            "files": [
                {
                    "methods": [{"methodId": "OrderService.refund"}],
                    "hotspots": [
                        {"riskTags": ["EXTERNAL_CALL_INSIDE_TRANSACTION"]}
                    ],
                }
            ]
        },
    }

    query = build_ast_retrieval_query(state, "service OrderService.java")

    assert "OrderService.refund" in query
    assert "事务内远程调用" in query
    assert "remote call in transaction" in query
    assert "OrderService.java" in query
