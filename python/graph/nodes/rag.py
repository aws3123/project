"""RAG 检索与分析节点 —— 从历史事故库中检索相关案例并用 LLM 分析风险关联。

本模块是主审查流水线中的 RAG（检索增强生成）节点，负责：
1. 根据代码变更的分类和路径信息构建检索查询
2. 调用统一检索服务（向量检索 + BM25 + RRF 融合 + 重排序）从知识库检索相关事故
3. 将检索结果 + 代码变更一起发给 LLM，让 LLM 分析"本次变更与历史事故的风险关联"

RAG 是什么？
  RAG = Retrieval-Augmented Generation（检索增强生成）
  类比：考试时允许翻书——先从书中找到相关内容（检索），再结合书本内容答题（生成）

为什么需要历史事故关联？
  如果本次代码变更与过去出过的事故类似，就能提前预警
  比如：历史上"缓存和数据库双写"导致过数据不一致，
  那这次如果也有类似模式，就应该提醒开发者注意
"""

from __future__ import annotations

import logging

# 安全地获取异常详情
from app.utils import safe_detail

# 导入应用配置
from config.settings import AppSettings

# RAG 领域纯函数
from domain.reviewers.rag_review import (
    build_code_metadata,
    build_context_text,
    build_rag_messages,
    build_retrieval_query,
    format_retrieval_results,
)

# 导入 diff 提取器（用于构建代码片段给 LLM 看）
from domain.shared.diff_extractor import build_diff_snippet

# 导入图状态和节点上下文
from graph.state import GraphState, NodeContext

# 导入 LLM 结构化输出异常
from llm.client import LLMStructuredOutputError

# 导入 Token 预算截断函数
from llm.token_counter import truncate_to_budget

# 导入 RAG 分析输出模型
from schemas.domain.llm_output import RAGAnalysisOutput

# 导入统一检索服务
from services.rag_retrieval_service import RagRetrievalService

logger = logging.getLogger(__name__)


def run_rag(state: GraphState, ctx: NodeContext) -> GraphState:
    """RAG 检索 + LLM 分析节点。

    输入：state["classification"] —— 代码分类结果
          state["diff_analysis"] —— diff 分析结果
          state["request"] —— 原始请求
    输出：state["rag_context"] —— 检索到的相关事故
          state["rag_analysis"] —— LLM 的风险关联分析
          state["rag_status"] —— RAG 状态
    """
    # 平凡变更 → 跳过 RAG 检索（triviality_check 已预填充结果）
    if state.get("trivial"):
        state["rag_context"] = []
        state["rag_analysis"] = ""
        state["rag_status"] = "NORMAL"
        return state

    settings = AppSettings()
    # 构建自然语言查询（从层级 + diff 路径拼接）
    nl_query = build_retrieval_query(state)

    # 提取代码元数据
    code_metadata = build_code_metadata(state)

    # 调用统一检索服务
    retrieval_service = RagRetrievalService(settings)
    try:
        fused, retrieval_status, retrieval_reason = retrieval_service.retrieve(
            nl_query, code_metadata, top_k=settings.top_k
        )
    except Exception as e:
        logger.error("RAG retrieval failed: %s", safe_detail(e))
        fused, retrieval_status, retrieval_reason = [], "DEGRADED", safe_detail(e)

    # 格式化检索结果为 rag_context（向后兼容）
    rag_findings = format_retrieval_results(fused)

    state["rag_context"] = rag_findings
    state["rag_status"] = retrieval_status
    state.setdefault("tool_logs", []).append(
        {
            "findings": rag_findings,
            "status": retrieval_status,
            "reason": retrieval_reason,
            "method": "vector+bm25+rrf+rerank",
        }
    )

    # LLM 分析：把检索结果 + 代码变更一起发给 LLM
    if ctx.llm_client is not None and fused:
        try:
            # 截断到 Token 预算内（避免超出 LLM 上下文窗口）
            budgeted = truncate_to_budget(
                fused, text_key="snippet", max_tokens=settings.rag_max_tokens
            )
            # 构建上下文文本
            context_text = build_context_text(budgeted)

            # 方法级 diff 提取（给 LLM 完整的方法体，而不是截断的行）
            diff_files = state.get("diff_analysis", {}).get("files", [])
            impact_radius = state.get("impact_radius")
            code_graph = state.get("code_graph")
            diff_snippet, _ = build_diff_snippet(
                diff_files,
                max_files=3,
                max_chars_per_file=1500,
                max_chars_total=3000,
                impact_radius=impact_radius,
                code_graph=code_graph,
            )

            # 构建 LLM 消息
            messages = build_rag_messages(context_text, diff_snippet)
            # 调用 LLM 结构化输出
            llm_result = ctx.llm_client.chat_structured(
                messages=messages,
                output_schema=RAGAnalysisOutput,
                max_tokens=1024,
            )
            state["rag_analysis"] = llm_result.get("risk_association", "")
            state["rag_status"] = "NORMAL"
        except LLMStructuredOutputError:
            # LLM 输出格式不正确 → 降级
            state["rag_analysis"] = ""
            state["rag_status"] = "DEGRADED"
    else:
        state["rag_analysis"] = ""
        state["rag_status"] = retrieval_status

    return state
