from __future__ import annotations

import json
from unittest.mock import patch

from config.settings import AppSettings
from repositories.keyword_index import search_incidents_keyword_local, write_keyword_index


@patch("repositories.keyword_index.es_client")
def test_write_keyword_index_round_trips_records(mock_es_client, tmp_path):
    index_path = tmp_path / "incident_keywords.jsonl"
    settings = AppSettings(chroma_keyword_index_path=str(index_path))

    rows = [
        {
            "id": "incident-a",
            "title": "incident-a",
            "snippet": "cache invalidation inside transaction",
            "source": "source-a",
            "service": "review",
            "tags": ["cache", "transaction"],
        }
    ]

    write_keyword_index(rows, settings)

    # Verify ES was called
    mock_es_client.index_documents.assert_called_once_with(rows, settings=settings)

    # Verify JSONL backup was still written
    content = index_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1
    assert json.loads(content[0])["title"] == "incident-a"


@patch("repositories.keyword_index.es_client")
def test_search_incidents_keyword_local_scores_token_overlap(mock_es_client, tmp_path):
    index_path = tmp_path / "incident_keywords.jsonl"

    mock_es_client.search_documents.return_value = [
        {
            "title": "incident-a",
            "snippet": "cache invalidation inside transaction",
            "source": "elasticsearch",
            "service": "review",
            "tags": ["cache", "transaction"],
            "image_urls": [],
            "image_texts": [],
            "score": 5.2,
        },
        {
            "title": "incident-b",
            "snippet": "controller validation only",
            "source": "elasticsearch",
            "service": "web",
            "tags": ["controller"],
            "image_urls": [],
            "image_texts": [],
            "score": 2.1,
        },
    ]

    rows = search_incidents_keyword_local(
        "cache transaction",
        top_k=2,
        settings=AppSettings(chroma_keyword_index_path=str(index_path)),
    )

    assert rows[0]["title"] == "incident-a"
    assert rows[0]["score"] > rows[1]["score"]
    # source should be normalised to "bm25" for backward compatibility
    assert rows[0]["source"] == "bm25"
