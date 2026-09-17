from __future__ import annotations

from services.document_loader import LoadedDocument
from services.incident_chunking import attach_figure_evidence, build_document_region_chunks


def test_build_document_regions_preserves_every_pdf_page_and_heading():
    document = LoadedDocument(
        text="",
        source_file="incident.pdf",
        format="pdf",
        pages=["# 总览\n" + "A" * 42, "# 修复\n" + "B" * 42],
    )

    chunks = build_document_region_chunks(document, max_chars=24, overlap=4)

    assert len(chunks) >= 4
    assert {chunk["doc_metadata"]["page_start"] for chunk in chunks} == {1, 2}
    assert chunks[0]["doc_metadata"]["section_title"] == "总览"
    assert any(chunk["doc_metadata"]["section_title"] == "修复" for chunk in chunks)
    assert all(chunk["doc_metadata"]["chunk_type"] == "section" for chunk in chunks)


def test_attach_figure_evidence_enriches_matching_page_only():
    document = LoadedDocument(
        text="",
        source_file="incident.pdf",
        format="pdf",
        pages=["第一页正文", "第二页正文"],
    )
    chunks = build_document_region_chunks(document)
    figure = {
        "nl_description": "订单服务调用库存服务",
        "doc_metadata": {
            "page_index": 1,
            "image_urls": ["https://minio/architecture.png"],
            "image_texts": ["OrderService InventoryService"],
            "image_relations": ["OrderService --calls--> InventoryService"],
            "image_bboxes": [{"page": 2, "bbox": [0, 0, 100, 100]}],
        },
    }

    attach_figure_evidence(chunks, [figure])

    assert "图像说明" not in chunks[0]["nl_description"]
    assert "订单服务调用库存服务" in chunks[1]["nl_description"]
    assert chunks[1]["doc_metadata"]["image_urls"] == ["https://minio/architecture.png"]
    assert chunks[1]["doc_metadata"]["image_relations"] == [
        "OrderService --calls--> InventoryService"
    ]
