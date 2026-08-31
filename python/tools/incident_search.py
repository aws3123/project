"""
事故搜索工具
========================

作用：
    根据代码变更的分类信息，从向量数据库（ChromaDB）中搜索相关的历史事故。
    帮助开发者了解类似变更曾经引发过什么问题。

什么是事故搜索？
    当代码变更涉及某个领域（如数据库、缓存、消息队列）时，
    系统会去向量库中查找过去在这个领域发生过的事故案例，
    作为审查的参考信息。

检查逻辑：
    1. 从输入中提取分类标签（layers）作为搜索关键词
    2. 调用 ChromaDB 进行向量相似度搜索
    3. 过滤掉相似度为 0 的结果
    4. 返回相关事故列表（包含标题、摘要、相关图片等）
"""

# annotations 延迟求值
from __future__ import annotations

# logging 记录日志
import logging

# safe_detail 安全地获取异常详情（避免泄露敏感信息）
from app.utils import safe_detail
# AppSettings 应用配置
from config.settings import AppSettings
# search_incidents_chromadb 从 ChromaDB 搜索事故
from repositories.chroma import search_incidents_chromadb
# 导入工具基础类型
from tools.base import Tool, ToolContext, ToolResult

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)


class IncidentSearchTool(Tool):
    """事故搜索工具。

    根据代码变更的分类信息，从向量库中搜索相关历史事故。
    """

    # 工具的唯一标识符
    name = "incident_search"

    def run(self, payload: dict, context: ToolContext) -> ToolResult:
        """执行事故搜索。

        参数 payload：
            - classification: 分类信息，包含 layers（标签列表）

        返回：
            ToolResult，包含搜索结果（findings）
        """
        # 加载应用配置（包含 top_k 等参数）
        settings = AppSettings()
        classification = payload.get("classification", {})

        try:
            # 将分类标签拼接为搜索关键词，如果没有标签则用 "general"
            query = " ".join(classification.get("layers", []) or ["general"])
            # 调用 ChromaDB 进行向量相似度搜索
            rows = search_incidents_chromadb(query, settings.top_k, settings=settings)
            default_source = "chromadb"  # 默认数据来源

            # 构建搜索结果列表
            findings = [
                {
                    "source": row.get("source", default_source),  # 数据来源
                    "topic": row.get("title", "unknown"),         # 事故标题
                    "snippet": row.get("snippet", ""),            # 事故摘要
                    "score": row.get("score", 0),                 # 相似度分数
                    "image_urls": row.get("image_urls", []),      # 相关图片 URL
                    "image_texts": row.get("image_texts", []),    # 图片描述文本
                    "citation": {                                 # 引用信息（用于溯源）
                        "source": row.get("source", default_source),
                        "title": row.get("title", "unknown"),
                        "snippet": row.get("snippet", ""),
                        "image_urls": row.get("image_urls", []),
                    },
                }
                for row in rows
                if float(row.get("score", 0)) > 0  # 只保留相似度大于 0 的结果
            ]

            # 返回正常结果
            return ToolResult(name=self.name, payload={"findings": findings, "status": "NORMAL", "reason": None})

        except Exception as exc:
            # 如果搜索失败，记录警告日志并返回降级结果
            reason = safe_detail(exc, max_len=120)  # 安全地获取异常信息
            logger.warning("Incident search degraded for task %s: %s", context.task_id, reason)
            return ToolResult(name=self.name, payload={"findings": [], "status": "DEGRADED", "reason": reason})
