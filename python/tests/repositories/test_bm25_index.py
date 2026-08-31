from __future__ import annotations

from unittest.mock import patch, MagicMock

from repositories.bm25_index import BM25Index


class TestBM25Index:
    @patch("repositories.bm25_index.es_client")
    def test_build_and_search(self, mock_es_client):
        docs = [
            {"id": "1", "title": "NullPointerException in UserService",
             "snippet": "UserService.getUserName() throws NPE when id is null",
             "source": "incident"},
            {"id": "2", "title": "Transaction rollback in OrderService",
             "snippet": "OrderService.createOrder() fails due to constraint violation",
             "source": "incident"},
            {"id": "3", "title": "Cache inconsistency in ProductCache",
             "snippet": "ProductCache returns stale data after inventory update",
             "source": "incident"},
        ]
        mock_es_client.search_documents.return_value = [
            {"id": "1", "title": "NullPointerException in UserService",
             "snippet": "UserService.getUserName() throws NPE when id is null",
             "source": "elasticsearch", "score": 5.2},
        ]

        index = BM25Index()
        index.build(docs)
        mock_es_client.index_documents.assert_called_once()

        results = index.search("NullPointerException UserService", top_k=2)
        assert len(results) >= 1
        assert results[0]["title"] == "NullPointerException in UserService"
        assert "score" in results[0]
        assert results[0]["score"] > 0
        # source should be normalised to "bm25" for backward compatibility
        assert results[0]["source"] == "bm25"

    @patch("repositories.bm25_index.es_client")
    def test_search_empty_index(self, mock_es_client):
        mock_es_client.search_documents.return_value = []

        index = BM25Index()
        results = index.search("anything", top_k=5)
        assert results == []

    @patch("repositories.bm25_index.es_client")
    def test_chinese_query(self, mock_es_client):
        mock_es_client.search_documents.return_value = [
            {"id": "1", "title": "用户服务空指针",
             "snippet": "用户查询接口传入空ID导致空指针异常",
             "source": "elasticsearch", "score": 3.1},
        ]

        index = BM25Index()
        index.build([])

        results = index.search("空指针", top_k=5)
        assert len(results) >= 1
        assert results[0]["title"] == "用户服务空指针"

    def test_save_is_noop(self, tmp_path):
        index = BM25Index()
        path = str(tmp_path / "bm25_index.pkl")
        # save should be a no-op and not raise
        index.save(path)

    def test_load_returns_none(self, tmp_path):
        result = BM25Index.load(str(tmp_path / "bm25_index.pkl"))
        assert result is None
