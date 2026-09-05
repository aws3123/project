"""图片/类图理解：OCR 为主，多模态 VL 为辅。

流程：
    1. run_ocr：用 Tesseract 对图块做 OCR，提取图内文字（作为 image_texts 与降级语义）。
    2. needs_vlm：根据 OCR 结果与图块来源判定「是否触发 VL」以及「是否判定为类图」。
       判定为类图/架构图的规则：OCR 文本为空白/过短，或包含 UML 结构关键词/关系符号。
    3. understand_vl：调用 qwen-vl 视觉模型，输出结构化类图描述
       {diagram_type, entities[], relations[], summary}，作为 nl_description 的语义主来源。

VL 不可用/超时时降级为 OCR 文本，不中断流程。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from config.settings import AppSettings
from services.pdf_processor import FigureBlock

logger = logging.getLogger(__name__)

# 触发 VL 并判为「类图/架构图」的结构关键词
_STRUCTURE_KEYWORDS = (
    "-->",
    "<|--",
    "..>",
    "++>",
    "<<interface>>",
    "<<abstract>>",
    "<<control>>",
    "继承",
    "聚合",
    "组合",
    "依赖",
    "实现",
    "菱形",
    "有向",
    "1..*",
    "0..*",
    "*..*",
    "er图",
    "类图",
    "架构图",
)

# 触发 VL 但保持「figure」不升级为类图的强语义词（普通截图/照片）
# 这里用于判断 OCR 文本是否「真的有内容但不像类图」。
_MIN_OCR_TOKENS = 10  # OCR 文本 token 数低于此 → 判定为「无有效信息」，触发 VL


class _DiagramSchema(BaseModel):
    """qwen-vl 输出的类图结构化结果。"""

    diagram_type: str = Field(default="unknown", description="图类型：class_diagram / architecture / er / other")
    entities: list[dict[str, str]] = Field(
        default_factory=list, description="实体列表，如类/表，含 name 与 type"
    )
    relations: list[dict[str, str]] = Field(
        default_factory=list, description="关系列表，含 source/target/kind"
    )
    summary: str = Field(default="", description="一段自然语言总结")


@dataclass
class ImageUnderstanding:
    """一次图块理解的结果。"""

    figure: FigureBlock
    ocr_text: str = ""
    is_class_diagram: bool = False
    structured: dict[str, Any] = field(default_factory=dict)
    vlm_used: bool = False
    status: str = "ocr_only"  # ocr_only | vlm_ok | vlm_unavailable | vlm_failed | upload_failed


def run_ocr(figure: FigureBlock, settings: AppSettings) -> str:
    """对图块执行 OCR，返回识别文字（失败返回空串，不抛错）。

    内联调用 pytesseract，自包含实现，避免依赖 scripts.ingest_incidents
    （后者存在遗留的环境性导入问题）。tesseract 二进制用 settings.tesseract_data_path
    指定 exe 路径（沿用现有约定）；未安装时失败返回空串，由 VL 兜底。
    """
    try:
        import pytesseract
        from PIL import Image as PILImage

        if settings.tesseract_data_path:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_data_path

        with PILImage.open(figure.image_path) as image:
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
        return (text or "").strip()
    except Exception as exc:  # 兜底，绝不让 OCR 异常中断流程
        logger.warning("OCR failed for %s: %s", figure.image_path, exc)
        return ""


def needs_vlm(ocr_text: str, figure: FigureBlock, settings: AppSettings) -> tuple[bool, bool]:
    """判定 (是否触发 VL, 是否判为类图)。OCR 为主，VL 为辅。"""
    if not settings.image_vl_fallback_enabled:
        return False, False

    # 整页渲染的扫描页：几乎必然需要 VL 理解
    if figure.kind == "page_render" and not ocr_text.strip():
        return True, True

    if not ocr_text.strip():
        return True, False

    token_count = len(ocr_text.split())
    low_text = token_count < _MIN_OCR_TOKENS

    # 结构关键词命中 → 判为类图/架构图，触发 VL
    lowered = ocr_text.lower()
    hit_structure = any(k.lower() in lowered for k in _STRUCTURE_KEYWORDS)

    if hit_structure:
        return True, True
    if low_text:
        # 文本过少、信息不足 → 触发 VL（可能是图标/无文字图形），但不强判类图
        return True, False
    return False, False


_VLM_PROMPT = (
    "你是一个软件架构分析助手。请分析这张图片（可能是 UML 类图/架构图/ER 图）：\n"
    "1. 识别图中出现的所有实体（类、接口、表、组件等），列出 name 和 type；\n"
    "2. 识别实体之间的关系（继承、实现、聚合、组合、依赖、关联等），列出 source、target、kind；\n"
    "3. 用一句中文概括这张图表达的核心结构（summary）。\n"
    '严格输出 JSON，格式：{"diagram_type": "...", '
    '"entities": [{"name": "...", "type": "..."}], '
    '"relations": [{"source": "...", "target": "...", "kind": "..."}], '
    '"summary": "..."}'
)


def understand_image(
    figure: FigureBlock,
    settings: AppSettings,
    llm_client,
) -> ImageUnderstanding:
    """图块理解入口：OCR 主 + VL 辅，返回结构化结果。"""
    ocr_text = run_ocr(figure, settings)
    figure.raw_ocr_text = ocr_text

    result = ImageUnderstanding(figure=figure, ocr_text=ocr_text)

    trigger_vlm, is_class_diagram = needs_vlm(ocr_text, figure, settings)
    result.is_class_diagram = is_class_diagram

    if not trigger_vlm:
        # OCR 足以支撑，不烧 VL token
        result.status = "ocr_only"
        return result

    # VL 辅助：生成结构化类图描述
    try:
        structured = llm_client.chat_vision_structured(
            _VLM_PROMPT,
            image_paths=[str(figure.image_path)],
            output_schema=_DiagramSchema,
            model=settings.vlm_model,
            timeout=settings.image_vlm_timeout,
        )
        result.structured = structured
        result.vlm_used = True
        result.status = "vlm_ok"
        if is_class_diagram and not structured.get("summary"):
            # VL 没给出总结但确认是类图 → 视为不可用
            result.status = "vlm_failed"
    except Exception as exc:
        logger.warning("VL understanding failed for %s: %s", figure.image_path, exc)
        result.status = "vlm_unavailable"
        result.vlm_used = True

    return result