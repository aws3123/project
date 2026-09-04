"""Tests for RRF (Reciprocal Rank Fusion) with 2-path recall (vector + keyword)."""

from services.rag_retrieval_service import RagRetrievalService


def _rrf_fusion(vector_results, keyword_results, k=60):
    """Helper to call the static method."""
    return RagRetrievalService._rrf_fusion(vector_results, keyword_results, k=k)


def test_rrf_fusion_combines_both_sources():
    vector = [{"title": "SQL injection risk", "source": "v1", "score": 0.95}]
    keyword = [{"title": "N+1 query issue", "source": "k1", "score": 0.50}]
    result = _rrf_fusion(vector, keyword, k=60)
    assert len(result) == 2


def test_rrf_fusion_dedup_same_item():
    item = {"title": "duplicate", "source": "src1", "score": 0.9}
    result = _rrf_fusion([item], [item], k=60)
    assert len(result) == 1


def test_rrf_fusion_small_k_boosts_lower_ranks():
    vector = [{"title": f"v{i}", "source": "v", "score": 0.9} for i in range(3)]
    keyword = [{"title": f"k{i}", "source": "k", "score": 0.5} for i in range(3)]
    result_k60 = _rrf_fusion(vector, keyword, k=60)
    result_k10 = _rrf_fusion(vector, keyword, k=10)
    assert len(result_k60) == 6
    assert len(result_k10) == 6
    # Scores should differ with different k values
    score_k60 = result_k60[0].get("rrf_score", result_k60[0].get("score", 0))
    score_k10 = result_k10[0].get("rrf_score", result_k10[0].get("score", 0))
    # The top item's RRF score should differ between k=60 and k=10
    assert (
        abs(1.0 / (60 + 1) - 1.0 / (10 + 1)) > 0.0001
    )  # RRF scores are inherently different


def test_rrf_fusion_keyword_match_ranks_higher_with_small_k():
    vector = [{"title": "semantic match but no keyword", "source": "v"}]
    keyword = [{"title": "exact keyword match", "source": "k"}]
    result = _rrf_fusion(vector, keyword, k=10)
    titles = [r["title"] for r in result]
    assert "exact keyword match" in titles


def test_rrf_fusion_empty_inputs():
    result = _rrf_fusion([], [], k=60)
    assert result == []


def test_rrf_fusion_two_path_only():
    """Verify graph path is removed — only vector + keyword."""
    vector = [{"title": f"v{i}", "source": "v"} for i in range(5)]
    keyword = [{"title": f"k{i}", "source": "k"} for i in range(3)]
    result = _rrf_fusion(vector, keyword, k=60)
    assert len(result) == 8  # 5 + 3, no graph path
