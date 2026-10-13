"""Convert completed graph state into the existing Java/API result contract."""

from __future__ import annotations

import logging

from app.utils import safe_detail
from graph.state import GraphState
from schemas.api.request import ReviewRequest
from schemas.api.result import Recommendation, ReviewResult, RiskBreakdown
from schemas.domain.enums import RAGStatus, TaskStatus, Tier
from services.image_service import ImageService
from services.image_url_replacer import replace_markdown_image_urls

logger = logging.getLogger(__name__)
SCORE_SCALE_FACTOR = 100


class ReviewResultMapper:
    def build(self, request: ReviewRequest, state: GraphState) -> ReviewResult:
        """将流水线最终状态转换为前端可消费的 ReviewResult。

        这个方法负责"翻译"工作：
        - 将内部状态（GraphState 字典）转换为结构化的 API 响应对象
        - 处理评分格式转换（0~1 → 0~100 百分制）
        - 组装风险细分、建议列表、图片引用等

        类比：
          就像厨师做完菜后的"摆盘"——菜（数据）已经做好了，
          这里负责把它装进漂亮的盘子里（结构化响应），端给客人（前端）。
        """

        # --- 转换风险评分细分为模型对象 ---
        breakdown_models: list[RiskBreakdown] = []
        for item in state.get("breakdown", []) or []:
            if isinstance(item, RiskBreakdown):
                breakdown_models.append(item)
                continue
            # 评分格式兼容：如果分数在 0~1 之间，转换为 0~100
            score = item.get("score", 0)
            if 0 <= score <= 1:
                score = int(round(score * SCORE_SCALE_FACTOR))
            else:
                score = int(round(score))
            breakdown_models.append(
                RiskBreakdown(dimension=item.get("dimension", "unknown"), score=score)
            )

        # --- 转换总风险评分 ---
        risk_score = state.get("risk_score", 50)
        if 0 <= risk_score <= 1:
            risk_score = int(round(risk_score * SCORE_SCALE_FACTOR))
        else:
            risk_score = int(round(risk_score))

        # 是否需要人工复核
        need_human_review = bool(
            state.get("need_human_review", False)
            or state.get("force_human_review", False)
        )
        task_status = (
            TaskStatus.NEED_REVIEW if need_human_review else TaskStatus.SUCCEEDED
        )

        # --- 组装最终的 ReviewResult ---
        result = ReviewResult(
            taskId=state["task_id"],
            status=task_status,
            riskScore=risk_score,
            riskSummary=state.get("summary", "No summary"),
            details=state.get("details", []),
            riskBreakdown=breakdown_models,
            recommendations=[
                Recommendation(title=rec.get("title", ""), detail=rec.get("detail", ""))
                for rec in state.get("recommendations", [])
            ]
            or [
                Recommendation(
                    title="summary", detail=state.get("summary", "No summary")
                )
            ],
            reportUrl=f"reports/{state['task_id']}.json",
            needHumanReview=need_human_review,
            ragStatus=state.get("rag_status", RAGStatus.NORMAL),
            tier=state.get("tier", Tier.LLM_ENHANCED),
            traceId=request.traceId or f"trace-{state['task_id']}",
            mode=request.mode.value,
        )

        self._replace_image_urls(result)
        return result

    def _replace_image_urls(self, result: ReviewResult) -> None:
        """替换结果文本中的图片占位 URL 为可访问的真实地址。

        LLM 生成的报告中可能包含 MinIO 图片链接，
        这里将占位符替换为前端可直接渲染的 Markdown 图片语法。
        如果替换失败也不影响主流程（catch 异常后仅记录警告）。
        """
        try:
            from config.settings import AppSettings

            settings = AppSettings()
            image_service = ImageService(settings)
            endpoint = settings.minio_endpoint.rstrip("/")
            bucket = settings.minio_image_bucket

            if result.riskSummary:
                result.riskSummary = replace_markdown_image_urls(
                    result.riskSummary, endpoint, bucket
                )
                result.riskSummary = image_service.replace_image_urls(
                    result.riskSummary
                )

            result.details = [
                image_service.replace_image_urls(
                    replace_markdown_image_urls(d, endpoint, bucket)
                )
                for d in result.details
            ]

            result.recommendations = [
                Recommendation(
                    title=image_service.replace_image_urls(
                        replace_markdown_image_urls(rec.title, endpoint, bucket)
                    ),
                    detail=image_service.replace_image_urls(
                        replace_markdown_image_urls(rec.detail, endpoint, bucket)
                    ),
                )
                for rec in result.recommendations
            ]
        except Exception as exc:
            logger.warning("Image URL replacement failed: %s", safe_detail(exc))
