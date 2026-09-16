from __future__ import annotations

from pathlib import Path

from config.settings import AppSettings
from repositories import chroma as chroma_repo


def test_bootstrap_chromadb_creates_collection_in_configured_path(monkeypatch):
    captured: dict[str, object] = {}

    class FakeCollection:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeClient:
        def __init__(self, path: str, settings=None) -> None:
            captured["path"] = path

        def get_or_create_collection(
            self, name: str, configuration=None, embedding_function=None
        ):
            captured["collection_name"] = name
            captured["configuration"] = configuration
            captured["embedding_function"] = embedding_function
            return FakeCollection(name)

    monkeypatch.setattr(chroma_repo.chromadb, "PersistentClient", FakeClient)

    settings = AppSettings(
        chroma_path="D:/Chroma",
        chroma_collection="incident_vectors",
    )

    collection = chroma_repo.bootstrap_chromadb(settings)

    assert captured == {
        "path": str(Path("D:/Chroma")),
        "collection_name": "incident_vectors",
        "configuration": {"hnsw": {"space": "cosine"}},
        "embedding_function": None,
    }
    assert collection.name == "incident_vectors"


def test_bootstrap_chromadb_uses_cosine_hnsw_space(monkeypatch):
    captured: dict[str, object] = {}

    class FakeCollection:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeClient:
        def __init__(self, path: str, settings=None) -> None:
            captured["path"] = path

        def get_or_create_collection(
            self, name: str, configuration=None, embedding_function=None
        ):
            captured["collection_name"] = name
            captured["configuration"] = configuration
            captured["embedding_function"] = embedding_function
            return FakeCollection(name)

    monkeypatch.setattr(chroma_repo.chromadb, "PersistentClient", FakeClient)

    collection = chroma_repo.bootstrap_chromadb(
        AppSettings(chroma_collection="incident_vectors")
    )

    assert captured["configuration"] == {"hnsw": {"space": "cosine"}}
    assert captured["embedding_function"] is None
    assert collection.name == "incident_vectors"


def test_upsert_incident_rows_omits_empty_tags_from_metadata(monkeypatch):
    captured: dict[str, object] = {}

    class FakeCollection:
        def upsert(self, ids, documents, embeddings, metadatas):
            captured["ids"] = ids
            captured["documents"] = documents
            captured["embeddings"] = embeddings
            captured["metadatas"] = metadatas

    monkeypatch.setattr(
        chroma_repo, "get_incident_collection", lambda settings=None: FakeCollection()
    )

    chroma_repo.upsert_incident_rows(
        [
            {
                "id": "1",
                "title": "incident-a",
                "snippet": "first snippet",
                "source": "source-a",
                "service": "svc",
                "tags": [],
                "embedding": [0.1, 0.2, 0.3],
            }
        ],
        settings=AppSettings(),
    )

    assert captured["ids"] == ["1"]
    assert captured["documents"] == ["first snippet"]
    assert captured["embeddings"] == [[0.1, 0.2, 0.3]]
    assert captured["metadatas"] == [
        {
            "title": "incident-a",
            "source": "source-a",
            "service": "svc",
        }
    ]


def test_search_incidents_chromadb_maps_distance_to_score(monkeypatch):
    class FakeCollection:
        def query(self, query_embeddings, n_results, include):
            assert query_embeddings == [[0.1, 0.2, 0.3]]
            assert n_results == 2
            assert include == ["documents", "metadatas", "distances"]
            return {
                "documents": [["first snippet", "second snippet"]],
                "metadatas": [
                    [
                        {
                            "title": "incident-a",
                            "source": "source-a",
                            "service": "svc",
                            "tags": ["cache"],
                        },
                        {
                            "title": "incident-b",
                            "source": "source-b",
                            "service": "svc",
                            "tags": ["tx"],
                        },
                    ]
                ],
                "distances": [[0.1, 0.4]],
            }

    monkeypatch.setattr(
        chroma_repo, "get_incident_collection", lambda settings=None: FakeCollection()
    )
    monkeypatch.setattr(
        chroma_repo, "_fetch_query_embedding", lambda query, settings: [0.1, 0.2, 0.3]
    )

    rows = chroma_repo.search_incidents_chromadb(
        "service cache",
        top_k=2,
        settings=AppSettings(top_k=2),
    )

    assert rows == [
        {
            "title": "incident-a",
            "snippet": "first snippet",
            "source": "source-a",
            "service": "svc",
            "tags": ["cache"],
            "score": 0.9,
        },
        {
            "title": "incident-b",
            "snippet": "second snippet",
            "source": "source-b",
            "service": "svc",
            "tags": ["tx"],
            "score": 0.6,
        },
    ]
