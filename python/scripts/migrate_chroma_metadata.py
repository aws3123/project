"""
ChromaDB 元数据迁移脚本 —— 给旧记录补上新字段，并同步到 Elasticsearch。

为什么要迁移？
    随着项目迭代，数据模型会不断增加新字段。
    比如最初 ChromaDB 中的事故记录只有 title、snippet 等基础字段，
    后来新增了 nl_description（自然语言描述）、code_content（代码内容）、
    entity_name（实体名称）等字段。
    但旧记录中并没有这些字段，查询时可能报错或返回空值。

这个脚本做什么？
    1. 扫描 ChromaDB 中的所有记录
    2. 找出缺少新字段的记录
    3. 为它们补上默认值
    4. 把更新后的记录同步到 Elasticsearch

使用方法：
    python -m scripts.migrate_chroma_metadata [--verbose]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 把项目根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import AppSettings
from repositories.chroma import get_incident_collection

logger = logging.getLogger(__name__)

# ── 新字段的默认值 ──
# 如果旧记录缺少某个字段，就用这里的默认值填充
# 这样查询时不会因为字段缺失而报错
DEFAULTS = {
    "nl_description": "",          # 自然语言描述（默认为空）
    "code_content": "",            # 代码内容（默认为空）
    "entity_name": "",             # 实体名称（如类名、方法名）
    "entity_kind": "unknown",      # 实体类型（class/method/function 等）
    "language": "unknown",         # 语言（如 java, python）
    "programming_language": "unknown",  # 编程语言
    "has_code": False,             # 是否包含代码
    "ast_status": "unknown",       # AST 解析状态
}

# 每条记录都应该有的字段列表（从 DEFAULTS 的键生成）
REQUIRED_FIELDS = list(DEFAULTS.keys())


def migrate_chroma(settings: AppSettings | None = None) -> dict:
    """迁移 ChromaDB 中的旧记录，为缺失字段补上默认值。

    流程：
        1. 从 ChromaDB 读取所有记录
        2. 逐条检查是否缺少 REQUIRED_FIELDS 中的字段
        3. 缺少的字段用 DEFAULTS 中的默认值填充
        4. 如果 nl_description 为空但有文档内容，用文档内容作为回退
        5. 分批 upsert（更新插入）回 ChromaDB

    参数:
        settings: 应用配置（可选）

    返回:
        迁移统计字典：{"total": 总记录数, "migrated": 迁移数, "skipped": 跳过数}
    """
    settings = settings or AppSettings()
    # 获取 ChromaDB 的事故记录集合
    collection = get_incident_collection(settings)

    # 获取所有记录（include 指定要返回的内容）
    # documents: 原始文本（用于向量检索的文本）
    # metadatas: 元数据字典列表
    all_data = collection.get(include=["documents", "metadatas"])
    ids = all_data.get("ids", [])
    documents = all_data.get("documents", [])
    metadatas = all_data.get("metadatas", [])

    if not ids:
        logger.info("No records found in ChromaDB collection '%s'", settings.chroma_collection)
        return {"total": 0, "migrated": 0, "skipped": 0}

    logger.info("Found %d records in ChromaDB", len(ids))

    # 找出需要迁移的记录
    to_migrate_ids: list[str] = []
    to_migrate_metadatas: list[dict] = []
    to_migrate_documents: list[str] = []

    # zip() 把多个列表"拉链式"配对，逐条处理
    # strict=False 表示允许长度不一致（不严格检查）
    for record_id, doc, meta in zip(ids, documents, metadatas, strict=False):
        if meta is None:
            meta = {}

        # 检查是否缺少任何必需字段
        needs_migration = False
        for field in REQUIRED_FIELDS:
            if field not in meta:
                needs_migration = True
                break

        if needs_migration:
            # 为缺失的字段填充默认值
            for field, default_val in DEFAULTS.items():
                if field not in meta:
                    meta[field] = default_val

            # 如果 nl_description 为空但文档内容存在，用文档内容作为回退
            # 这样至少能用文档内容做语义检索
            if not meta.get("nl_description") and doc:
                meta["nl_description"] = doc

            to_migrate_ids.append(record_id)
            to_migrate_metadatas.append(meta)
            to_migrate_documents.append(doc)

    if not to_migrate_ids:
        logger.info("All records already have new fields. No migration needed.")
        return {"total": len(ids), "migrated": 0, "skipped": len(ids)}

    logger.info("Migrating %d records (out of %d total)...", len(to_migrate_ids), len(ids))

    # 分批 upsert（每批 100 条）
    # 为什么要分批？因为一次请求太多数据可能导致超时或内存溢出
    batch_size = 100
    for i in range(0, len(to_migrate_ids), batch_size):
        # 用列表切片取出当前批的数据
        batch_ids = to_migrate_ids[i:i + batch_size]
        batch_docs = to_migrate_documents[i:i + batch_size]
        batch_metas = to_migrate_metadatas[i:i + batch_size]

        # upsert = update + insert
        # 如果记录已存在则更新，不存在则插入
        collection.upsert(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas,
        )
        logger.info("  Migrated batch %d-%d/%d", i + 1, min(i + batch_size, len(to_migrate_ids)), len(to_migrate_ids))

    stats = {
        "total": len(ids),
        "migrated": len(to_migrate_ids),
        "skipped": len(ids) - len(to_migrate_ids),
    }
    return stats


def migrate_es(settings: AppSettings | None = None) -> dict:
    """把 ChromaDB 中的记录同步到 Elasticsearch。

    为什么要同步？
        我们的 RAG 系统使用"混合检索"：
        - ChromaDB 负责语义向量检索
        - Elasticsearch 负责关键词检索（BM25）
        两边的数据需要保持一致，否则关键词检索会找不到旧记录。

    流程：
        1. 从 ChromaDB 读取所有记录
        2. 为每条记录组装 ES 文档格式（包含新旧字段）
        3. 用 bulk API 批量写入 ES

    参数:
        settings: 应用配置（可选）

    返回:
        同步统计：{"synced": 成功数} 或 {"synced": 0, "error": "错误信息"}
    """
    settings = settings or AppSettings()

    try:
        # 延迟导入 ES 相关模块（只在需要时才加载）
        from elasticsearch import helpers
        from repositories.es_client import get_es_client, ensure_index

        # 确保 ES 索引存在（不存在则创建）
        ensure_index(settings)
        client = get_es_client(settings)
        index_name = settings.es_index_name

        # 从 ChromaDB 获取所有记录
        collection = get_incident_collection(settings)
        all_data = collection.get(include=["documents", "metadatas"])
        ids = all_data.get("ids", [])
        documents = all_data.get("documents", [])
        metadatas = all_data.get("metadatas", [])

        if not ids:
            logger.info("No records to sync to ES")
            return {"synced": 0}

        # 构建 ES 批量操作列表
        # 每条记录对应一个 action 字典
        actions = []
        for record_id, doc, meta in zip(ids, documents, metadatas, strict=False):
            if meta is None:
                meta = {}

            # 组装 ES 文档（把 ChromaDB 的元数据映射到 ES 的字段结构）
            es_doc = {
                "title": meta.get("title", "unknown"),
                "snippet": doc or "",              # ES 中的检索文本
                "source": meta.get("source", "unknown"),
                "service": meta.get("service"),
                "tags": meta.get("tags", []),
                "image_urls": meta.get("image_urls", []),
                "image_texts": meta.get("image_texts", []),
                # 新字段（带默认值）
                "nl_description": meta.get("nl_description", doc or ""),
                "code_content": meta.get("code_content", ""),
                "entity_name": meta.get("entity_name", ""),
                "entity_kind": meta.get("entity_kind", "unknown"),
                "language": meta.get("language", "unknown"),
                "programming_language": meta.get("programming_language", "unknown"),
                "has_code": meta.get("has_code", False),
                "ast_status": meta.get("ast_status", "unknown"),
            }
            actions.append({
                "_index": index_name,    # ES 索引名
                "_id": record_id,        # 文档 ID（与 ChromaDB 一致）
                "_source": es_doc,       # 文档内容
            })

        if actions:
            # helpers.bulk 是 ES 的批量操作 API，比逐条写入快几十倍
            # raise_on_error=False 表示遇到错误不抛异常，而是返回错误列表
            success, errors = helpers.bulk(client, actions, raise_on_error=False)
            if errors:
                logger.warning("ES sync had %d errors: %s", len(errors), errors[:3])
            logger.info("Synced %d records to ES '%s'", success, index_name)
            return {"synced": success}

        return {"synced": 0}

    except Exception as e:
        # ES 同步失败不是致命错误（ChromaDB 迁移已完成）
        logger.warning("ES sync failed (non-fatal): %s", e)
        return {"synced": 0, "error": str(e)}


def run_migration(settings: AppSettings | None = None) -> None:
    """执行完整的迁移流程：先迁移 ChromaDB，再同步到 ES。"""
    settings = settings or AppSettings()

    print("=" * 60)
    print("ChromaDB Metadata Migration")
    print("=" * 60)

    # 第 1 步：迁移 ChromaDB 记录
    print("\n[1/2] Migrating ChromaDB records...")
    chroma_stats = migrate_chroma(settings)
    print(f"  Total records:  {chroma_stats['total']}")
    print(f"  Migrated:       {chroma_stats['migrated']}")
    print(f"  Already OK:     {chroma_stats['skipped']}")

    # 第 2 步：同步到 Elasticsearch
    print("\n[2/2] Syncing to Elasticsearch...")
    es_stats = migrate_es(settings)
    print(f"  Synced to ES:   {es_stats.get('synced', 0)}")
    if "error" in es_stats:
        print(f"  Errors:         {es_stats['error']}")

    print("\n" + "=" * 60)
    print("Migration complete.")
    print("=" * 60)


def main():
    """脚本入口：解析参数，执行迁移。"""
    import argparse

    parser = argparse.ArgumentParser(description="Migrate old ChromaDB records")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # --verbose 时用 DEBUG 级别，否则用 INFO
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    run_migration(AppSettings())


if __name__ == "__main__":
    main()
