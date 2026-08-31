from __future__ import annotations

import json

from config.settings import AppSettings
from scripts import seed_incidents as seed_module


def test_seed_incidents_from_json_upserts_rows_and_writes_keywords(monkeypatch, tmp_path):
    input_path = tmp_path / "incidents.json"
    input_path.write_text(
        json.dumps([
            {
                "title": "incident-a",
                "snippet": "cache invalidation inside transaction",
                "source": "source-a",
                "service": "review",
                "tags": ["cache", "transaction"],
            }
        ], ensure_ascii=False),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}
    monkeypatch.setattr(seed_module, "_fetch_query_embedding", lambda text, settings: [0.1, 0.2, 0.3])
    monkeypatch.setattr(seed_module, "upsert_incident_rows", lambda rows, settings=None: captured.setdefault("rows", rows))
    monkeypatch.setattr(seed_module, "write_keyword_index", lambda rows, settings=None: captured.setdefault("keyword_rows", rows))

    seed_module.seed_incidents_from_json(
        input_path,
        AppSettings(
            chroma_path=str(tmp_path / "chroma"),
            chroma_keyword_index_path=str(tmp_path / "incident_keywords.jsonl"),
        ),
    )

    assert captured["rows"] == [
        {
            "id": "source-a:incident-a",
            "title": "incident-a",
            "snippet": "cache invalidation inside transaction",
            "source": "source-a",
            "service": "review",
            "tags": ["cache", "transaction"],
            "embedding": [0.1, 0.2, 0.3],
        }
    ]
    assert captured["keyword_rows"] == captured["rows"]
