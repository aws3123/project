import json

from app.routers.incidents import ApprovedIncidentDraft, _ingest


def test_approved_feedback_incident_is_upserted_with_ast_context(monkeypatch):
    embedded = []
    chroma = []
    elastic = []
    monkeypatch.setattr("app.routers.incidents.generate_embeddings", lambda chunks, settings: embedded.extend(chunks))
    monkeypatch.setattr("app.routers.incidents.upsert_unified_chunks", lambda chunks, settings: chroma.extend(chunks))
    monkeypatch.setattr("app.routers.incidents.index_unified_chunks", lambda chunks, settings: elastic.extend(chunks))

    draft = ApprovedIncidentDraft(
        draftId=12,
        feedbackId=5,
        taskId="task-1",
        incidentContent="支付扣款接口在事务中调用远程服务导致超时后数据不一致。",
        feedbackSnapshotJson=json.dumps({"category": "遗漏风险"}),
        astSnapshotJson=json.dumps({"diffContent": "+ @Transactional\n+ client.call();"}),
        reviewSnapshotJson=json.dumps({"riskSummary": "远程调用位于事务内"}),
    )

    _ingest(draft, settings=object())

    assert len(embedded) == len(chroma) == len(elastic) == 1
    chunk = chroma[0]
    assert chunk["id"] == "feedback-incident:12"
    assert "@Transactional" in chunk["code_content"]
    assert chunk["ast_metadata"]["entity_kind"] == "historical_incident"
    assert chunk["doc_metadata"]["task_id"] == "task-1"
