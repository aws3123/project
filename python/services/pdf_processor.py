"""PDF 混合文档图块抽取。

把 PDF 渲染成页面图像、定位内嵌图片/矢量图/扫描页，产出「图块」候选。
图块是后续 OCR/多模态理解的输入：类图、架构图、代码截图往往以图片形态
存在于 PDF 中，文本层提取不到，必须靠这里渲染出来。

依赖：PyMuPDF（pymupdf），自带 MuPDF，无需额外 C 依赖。
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import AppSettings

logger = logging.getLogger(__name__)


@dataclass
class FigureBlock:
    """PDF 中的一个候选图块。

    kind 表示图块来源：
        - embedded_raster: 内嵌位图（最早的判定，仅占位标识）
        - region_render:   在整页渲染图上裁剪出图区域（含矢量叠加，首选路径）
        - page_render:     整页渲染（扫描型/矢量图页）
    """

    page_index: int
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1) 页坐标
    image_path: Path  # 已保存的 PNG 渲染图，供 OCR / VL 使用
    kind: str = "region_render"
    page_text: str = ""  # 该页文本层，仅作补充上下文，不入 embedding 主文本
    raw_ocr_text: str = ""  # 由 image_understanding 填充
    is_class_diagram: bool = False

    def __post_init__(self) -> None:
        self.image_path = Path(self.image_path)


class PdfProcessor:
    """渲染 PDF 并抽取图块候选。"""

    # 判定「矢量图/扫描页」的启发式阈值
    _VECTOR_TEXT_THRESHOLD = 200  # 页文本字符数低于此且框线多 → 视为矢量图页
    _VECTOR_DRAWINGS_THRESHOLD = 4  # 页矢量框线数超过此

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings()

    def load_and_render(self, pdf_path: str) -> tuple[list[str], list[FigureBlock]]:
        """渲染 PDF，返回 (每页文本列表, 图块候选列表)。

        若 PyMuPDF 不可用，抛 ImportError（由调用方回退到旧 pypdf 逻辑）。
        """
        import pymupdf  # noqa: PLC0415 - 延迟导入以便优雅回退

        pdf_path = str(pdf_path)
        render_dir = Path(tempfile.mkdtemp(prefix="pdf_figures_"))
        zoom = self.settings.pdf_render_dpi / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)
        max_pages = self.settings.pdf_figure_max_pages

        pages_text: list[str] = []
        figures: list[FigureBlock] = []

        doc = pymupdf.open(pdf_path)
        try:
            for pno, page in enumerate(doc):
                if max_pages and pno >= max_pages:
                    logger.warning(
                        "PDF exceeds max_pages=%d, skipping figure extraction for page %d+",
                        max_pages,
                        max_pages,
                    )
                    break
                text = page.get_text("text") or ""
                pages_text.append(text)
                figures.extend(
                    self._figures_for_page(page, pno, text, render_dir, matrix)
                )
        finally:
            doc.close()

        logger.info("PDF %s: %d pages, %d figure candidates", pdf_path, len(pages_text), len(figures))
        return pages_text, figures

    def _figures_for_page(self, page, pno: int, text: str, render_dir: Path, matrix) -> list[FigureBlock]:
        """识别单页内的图块候选。"""
        import pymupdf  # noqa: PLC0415

        min_area = self.settings.pdf_figure_min_area
        figures: list[FigureBlock] = []

        # 1) 内嵌位图区域（优先路径：渲染该区域，含可能的矢量叠加）
        embedded_rects: list = []
        for img in page.get_images(full=True):
            xref = img[0]
            for r in page.get_image_rects(xref):
                if (r.width * r.height) >= min_area:
                    embedded_rects.append(pymupdf.Rect(r))

        if embedded_rects:
            for i, rect in enumerate(embedded_rects):
                # clip: 页坐标矩形，只渲染该区域，得到清晰图块（含矢量叠加）
                pix = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
                img_path = render_dir / f"page_{pno}_img_{i}.png"
                pix.save(str(img_path))
                figures.append(
                    FigureBlock(
                        page_index=pno,
                        bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                        image_path=img_path,
                        kind="region_render",
                        page_text=text,
                    )
                )
            return figures

        # 2) 无内嵌位图 → 判断是否整页即图（扫描页 / 矢量图页）
        drawings = page.get_drawings() or []
        if not text.strip():
            # 扫描型 PDF：整页是图
            figures.append(self._render_page(page, pno, render_dir, matrix, "scan"))
        elif len(text.strip()) < self._VECTOR_TEXT_THRESHOLD and len(drawings) >= self._VECTOR_DRAWINGS_THRESHOLD:
            # 矢量图页：文本稀少但框线密集
            figures.append(self._render_page(page, pno, render_dir, matrix, "vector"))

        return figures

    def _render_page(self, page, pno: int, render_dir: Path, matrix, tag: str) -> FigureBlock:
        """整页渲染为一个图块。"""
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img_path = render_dir / f"page_{pno}_{tag}.png"
        pix.save(str(img_path))
        return FigureBlock(
            page_index=pno,
            bbox=(0, 0, page.rect.width, page.rect.height),
            image_path=img_path,
            kind="page_render",
            page_text=page.get_text("text") or "",
        )