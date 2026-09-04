"""
种子事故数据导入脚本 —— 把 JSON 格式的事故记录写入 ChromaDB（向量库）和 Elasticsearch（关键词索引）。

什么是"种子数据"（Seed Data）？
    种子数据就是系统初始化时需要预置的基础数据。
    就像游戏开局时自带的装备——不是用户产生的，而是开发者预设的。
    这里我们预设了一批真实的生产事故报告，用于 RAG 检索。

这个脚本做什么？
    1. 读取一个 JSON 文件，里面包含多条事故记录
    2. 对每条记录：提取文本 → 调用嵌入模型生成向量 → 组装成一行数据
    3. 把所有数据批量写入 ChromaDB（用于语义向量检索）
    4. 同时写入 Elasticsearch 的关键词索引（用于 BM25 关键词检索）

为什么要同时写入两个库？
    因为我们的 RAG 系统使用"混合检索"：向量检索（语义相似）+ 关键词检索（精确匹配）
    两路检索的结果通过 RRF（Reciprocal Rank Fusion）算法融合，效果更好。

使用方法：
    python -m scripts.seed_incidents --input data/incidents.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── 路径设置 ──
# 下面 3 行的作用：把项目根目录加入 Python 的模块搜索路径
# 这样我们就可以用 "from config.settings import ..." 这样的绝对导入
# Path(__file__) 是当前脚本的路径，.resolve() 转成绝对路径，.parents[1] 取上两级目录（即 python/）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 导入项目模块 ──
from config.settings import AppSettings
from repositories.chroma import bootstrap_chromadb, upsert_incident_rows
from repositories.db import _fetch_query_embedding
from repositories.keyword_index import write_keyword_index
from services.image_service import ImageService


def _load_image_mapping(settings: AppSettings) -> dict:
    """加载图片映射文件（如果存在的话）。

    图片映射文件记录了每个事故文档中包含哪些图片、
    每张图片的 MinIO 存储 URL 和 OCR 识别出的文字内容。

    返回:
        一个嵌套字典，结构为：{文档名: {图片名: {url, ocr_text, source_doc}}}
        如果映射文件不存在，返回空字典。
    """
    image_service = ImageService(settings)
    return image_service.get_all_mappings()


def seed_incidents_from_json(input_path: Path, settings: AppSettings) -> None:
    """从 JSON 文件读取事故记录，生成向量，写入 ChromaDB 和 Elasticsearch。

    整体流程：
        1. 初始化 ChromaDB（确保集合存在）
        2. 读取 JSON 文件中的所有事故记录
        3. 加载图片映射（如果有的话，把图片 OCR 文字也加入检索内容）
        4. 对每条记录：生成嵌入向量 → 组装成一行数据
        5. 批量写入 ChromaDB + 关键词索引

    参数:
        input_path: JSON 文件的路径
        settings: 应用配置对象，包含数据库连接信息等
    """
    # 第 1 步：初始化 ChromaDB（创建集合等）
    bootstrap_chromadb(settings)

    # 第 2 步：读取 JSON 文件
    # read_text 读取文件全部内容，json.loads 把 JSON 字符串解析成 Python 对象（列表/字典）
    records = json.loads(input_path.read_text(encoding="utf-8"))

    # 第 3 步：加载图片映射
    image_mapping = _load_image_mapping(settings)

    # rows 是最终要写入数据库的数据行列表
    rows: list[dict] = []

    for record in records:
        # 每条记录至少包含 title（标题）和 snippet（摘要/描述）
        snippet = record["snippet"]
        image_urls: list[str] = []  # 事故相关图片的 URL 列表
        image_texts: list[str] = []  # 图片 OCR 识别出的文字列表

        # 检查这条记录是否有关联图片
        images = record.get("images", [])  # .get 带默认值，如果 key 不存在返回空列表
        if images:
            # 根据 source 字段找到对应的图片映射
            # 例如 source="incident-review-013" → 映射文件中的 key 是 "incident-013"
            source = record.get("source", "")
            source_doc = source.replace("incident-review-", "incident-")
            doc_mapping = image_mapping.get(source_doc, {})

            for img_name in images:
                # 从映射中查找这张图片的信息
                img_info = doc_mapping.get(img_name, {})
                url = img_info.get("url", "")  # MinIO 存储地址
                ocr_text = img_info.get("ocr_text", "")  # OCR 识别的文字

                if url:
                    image_urls.append(url)
                if ocr_text:
                    image_texts.append(ocr_text)

            # 如果有 OCR 文字，把它追加到摘要后面
            # 这样检索时图片中的文字内容也能被匹配到
            if image_texts:
                snippet += "\n[图片内容: " + " | ".join(image_texts) + "]"

        # 组装一行完整的数据记录
        rows.append(
            {
                # id 是这条记录在 ChromaDB 中的唯一标识
                # 格式："来源:标题"，例如 "incident-review-013:Google Cloud NPE..."
                "id": f"{record['source']}:{record['title']}",
                "title": record["title"],  # 事故标题
                "snippet": snippet,  # 事故描述（可能包含 OCR 文字）
                "source": record["source"],  # 来源标识
                "service": record.get("service"),  # 所属服务/领域（如 "infra", "saas"）
                "tags": record.get("tags", []),  # 标签列表（如 ["cloud", "dns"]）
                # 调用嵌入模型把文本转成向量（1536维的浮点数数组）
                # 这个向量会被存入 ChromaDB，用于后续的语义相似度检索
                "embedding": _fetch_query_embedding(record["snippet"], settings),
                "image_urls": image_urls,  # 关联图片 URL 列表
                "image_texts": image_texts,  # 图片 OCR 文字列表
            }
        )

    # 第 5 步：批量写入 ChromaDB（向量检索用）
    upsert_incident_rows(rows, settings)

    # 同时写入 Elasticsearch 的关键词索引（BM25 检索用）
    write_keyword_index(rows, settings)


def main() -> None:
    """脚本入口：解析命令行参数，执行种子数据导入。"""
    parser = argparse.ArgumentParser()
    # --input 是必选参数，指定 JSON 文件路径
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    settings = AppSettings()
    seed_incidents_from_json(Path(args.input), settings)


# 这行是 Python 脚本的标准入口守卫
# 含义：只有直接运行这个脚本时才执行 main()，被 import 时不执行
# 这样其他模块 import 这个文件时不会意外触发脚本逻辑
if __name__ == "__main__":
    main()
