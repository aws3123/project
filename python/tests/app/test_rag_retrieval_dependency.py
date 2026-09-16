from app import dependencies


def test_rag_retrieval_service_is_process_singleton(monkeypatch):
    created = []

    class FakeRagRetrievalService:
        def __init__(self, settings):
            created.append(settings)

    monkeypatch.setattr(dependencies, "RagRetrievalService", FakeRagRetrievalService)
    monkeypatch.setattr(dependencies, "_rag_retrieval_service", None)
    monkeypatch.setattr(dependencies, "get_settings", lambda: object())

    first = dependencies.get_rag_retrieval_service()
    second = dependencies.get_rag_retrieval_service()

    assert first is second
    assert len(created) == 1
