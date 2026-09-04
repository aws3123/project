"""
事故文档摄入脚本 —— 扫描事故文档目录，对其中的图片做 OCR 文字识别，上传到 MinIO 对象存储，生成映射文件。

什么是 OCR？
    OCR（Optical Character Recognition，光学字符识别）= 从图片中提取文字。
    比如事故报告中可能包含错误截图、架构图，OCR 能把图中的文字提取出来，
    让这些文字也能被检索到。本项目使用 Tesseract 作为 OCR 引擎。

什么是 MinIO？
    MinIO 是一个开源的对象存储服务（类似 AWS S3）。
    我们用它来存储事故文档中的图片，然后通过 URL 访问。

这个脚本做什么？
    1. 扫描指定的文档目录，找到所有事故子目录
    2. 对每个子目录中的图片：
       a. 用 Tesseract OCR 提取文字
       b. 上传图片到 MinIO，获取访问 URL
    3. 生成一个映射文件，记录：哪个文档的哪张图片 → URL + OCR 文字

目录结构示例：
    docs_dir/
      incident-001/
        description.txt          ← 事故描述文字
        architecture-diagram.png ← 架构图（会被 OCR + 上传）
        error-stacktrace.png     ← 错误堆栈截图
      incident-002/
        description.txt
        monitoring-dashboard.jpg

使用方法：
    python -m scripts.ingest_incidents [--docs-dir /path/to/docs]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ── 路径设置 ──
# 把项目根目录（python/）加入 sys.path，使我们可以用绝对导入
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.image.service import ImageService

from config.settings import AppSettings

logger = logging.getLogger(__name__)

# 支持的图片扩展名集合
# set（集合）的查找速度比 list 快，适合做"判断某个元素是否在其中"的检查
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _run_ocr(image_path: Path, settings: AppSettings) -> str:
    """对一张图片执行 OCR 文字识别，返回识别出的文字。

    工作原理：
        1. 用 Pillow（PIL）库打开图片
        2. 调用 pytesseract 库（Tesseract OCR 的 Python 封装）识别文字
        3. 同时识别中文（chi_sim）和英文（eng）

    参数:
        image_path: 图片文件的路径
        settings: 应用配置，可能包含 tesseract_data_path（Tesseract 引擎的路径）

    返回:
        识别出的文字（已去除首尾空白）。如果失败则返回空字符串。

    注意：
        - 如果 pytesseract 或 Pillow 没安装，会跳过（返回空字符串）
        - 如果 OCR 过程出错，也会跳过（不会中断整个流程）
    """
    try:
        # 延迟导入（lazy import）：只在实际需要时才导入这些库
        # 好处：如果用户不需要 OCR 功能，就不必安装这些依赖
        import pytesseract
        from PIL import Image

        # 如果配置中指定了 Tesseract 的数据路径（如语言包位置），设置它
        if settings.tesseract_data_path:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_data_path

        # 打开图片并执行 OCR
        image = Image.open(image_path)
        # lang="chi_sim+eng" 表示同时识别简体中文和英文
        text = pytesseract.image_to_string(image, lang="chi_sim+eng")
        return text.strip()  # strip() 去除首尾的空白字符和换行
    except ImportError:
        # pytesseract 或 Pillow 没安装，给出警告但不中断
        logger.warning(
            "pytesseract or Pillow not installed, skipping OCR for %s", image_path
        )
        return ""
    except Exception as exc:
        # OCR 可能因为图片损坏等原因失败，记录警告但不中断
        logger.warning("OCR failed for %s: %s", image_path, exc)
        return ""


def ingest_incident_docs(docs_dir: Path, settings: AppSettings | None = None) -> dict:
    """扫描事故文档目录，对图片做 OCR + 上传，生成映射。

    整体流程：
        1. 遍历 docs_dir 下的每个子目录（每个子目录代表一个事故文档）
        2. 在每个子目录中找到所有图片文件
        3. 对每张图片：OCR 识别文字 → 上传到 MinIO → 获取 URL
        4. 把所有映射关系保存到文件

    参数:
        docs_dir: 事故文档的根目录
        settings: 应用配置（可选，不传则自动创建）

    返回:
        完整的映射字典，结构为：
        {
            "incident-001": {
                "architecture-diagram.png": {
                    "url": "http://minio:9000/...",
                    "ocr_text": "识别出的文字...",
                    "source_doc": "incident-001"
                },
                ...
            },
            ...
        }
    """
    settings = settings or AppSettings()
    image_service = ImageService(settings)
    # mapping 存储最终的映射关系
    mapping: dict[str, dict[str, dict]] = {}

    # 检查目录是否存在
    if not docs_dir.exists():
        logger.warning("Incident docs directory does not exist: %s", docs_dir)
        return mapping

    # 遍历每个子目录（sorted 保证顺序一致，方便调试）
    for doc_dir in sorted(docs_dir.iterdir()):
        # 只处理目录，跳过文件
        if not doc_dir.is_dir():
            continue

        # source_doc 是子目录名，如 "incident-001"
        source_doc = doc_dir.name
        # doc_mapping 记录这个文档中所有图片的映射
        doc_mapping: dict[str, dict] = {}
        logger.info("Processing incident document: %s", source_doc)

        # 遍历子目录中的每个文件
        for image_file in sorted(doc_dir.iterdir()):
            # 只处理图片文件（通过扩展名判断）
            if image_file.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            logger.info("  Processing image: %s", image_file.name)

            # 第 1 步：对图片执行 OCR
            ocr_text = _run_ocr(image_file, settings)

            # 第 2 步：上传图片到 MinIO
            try:
                url = image_service.upload_image(image_file, source_doc)
            except Exception as exc:
                logger.error("  Failed to upload %s: %s", image_file.name, exc)
                url = ""  # 上传失败时 URL 为空

            # 第 3 步：记录这张图片的映射信息
            doc_mapping[image_file.name] = {
                "url": url,  # MinIO 存储地址
                "ocr_text": ocr_text,  # OCR 识别出的文字
                "source_doc": source_doc,  # 所属文档名
            }

        # 如果这个文档有图片，把映射加入总映射
        if doc_mapping:
            mapping[source_doc] = doc_mapping
            logger.info("  Ingested %d images for %s", len(doc_mapping), source_doc)

    # 把所有映射信息保存到文件（后续 seed_incidents 脚本会读取）
    image_service.save_mapping(mapping)
    logger.info("Ingestion complete. Total documents: %d", len(mapping))
    return mapping


def main() -> None:
    """脚本入口：解析命令行参数，执行事故文档摄入。"""
    parser = argparse.ArgumentParser(
        description="Ingest incident documents: OCR images, upload to MinIO, generate mapping."
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=None,
        help="Root directory containing incident document subdirectories (default: from settings)",
    )
    args = parser.parse_args()

    settings = AppSettings()
    # 如果命令行没指定 --docs-dir，就从配置中读取默认路径
    docs_dir = args.docs_dir or Path(settings.incident_docs_dir)

    # 配置日志格式：时间 [级别] 模块名: 消息
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    ingest_incident_docs(docs_dir, settings)


if __name__ == "__main__":
    main()
