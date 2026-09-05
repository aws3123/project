"""
代码库索引脚本 —— 扫描项目源代码，提取代码块，生成向量，存入 ChromaDB。

为什么要索引代码库？
    当 AI 审查代码时，它需要知道"这段代码属于哪个类？调用了哪些方法？"
    通过预先索引代码库，我们可以：
    1. 用自然语言搜索代码（如"处理用户认证的函数"）
    2. 在审查时自动检索相关代码上下文
    3. 理解代码之间的依赖关系

这个脚本做什么？
    1. 扫描项目中多种语言的源代码文件（Java/Python/TypeScript）
    2. 从每个文件中提取"代码块"（类、方法、函数）
    3. 对每个代码块调用嵌入模型生成向量
    4. 批量存入 ChromaDB 向量数据库

代码提取策略：
    - Python: 使用 AST（抽象语法树）精确解析 → 最准确
    - Java/TypeScript: 使用正则表达式匹配 → 简单但够用

使用方法：
    python -m scripts.index_codebase
"""

from __future__ import annotations

import ast  # Python 的 AST 模块：把 Python 源码解析成树状结构
import json
import logging
import re  # 正则表达式库：用于模式匹配
import sys
from pathlib import Path
from typing import Any

# ── 路径设置 ──
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import AppSettings
from repositories.chroma import get_chroma_client
from repositories.db import _fetch_query_embedding

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── 代码根目录配置 ──
# 每个元素是 (语言, 目录路径) 的元组
# 脚本会扫描这些目录，按语言选择对应的解析器
CODE_ROOTS = [
    ("java", ROOT.parent / "backend/src/main/java"),
    ("python", ROOT / "app"),
    ("python", ROOT / "graph"),
    ("python", ROOT / "repositories"),
    ("python", ROOT / "tools"),
    ("python", ROOT / "scripts"),
    ("python", ROOT / "services"),
    ("python", ROOT / "mq"),
    ("typescript", ROOT.parent / "frontend/src"),
]


# ============================================================
# 代码块提取器（按语言分）
# ============================================================


def _extract_python_blocks(filepath: Path) -> list[dict]:
    """从 Python 文件中提取类和函数（使用 AST 精确解析）。

    什么是 AST？
        AST（Abstract Syntax Tree，抽象语法树）是源码的结构化表示。
        比如 "def foo():" 会被解析成一个 FunctionDef 节点，
        包含函数名、参数、行号等信息。
        AST 解析比正则表达式更准确，不会误匹配注释中的代码。

    参数:
        filepath: Python 文件路径

    返回:
        代码块列表，每个元素包含：
        {name, kind, file, start_line, end_line, content, language}
    """
    try:
        # 读取文件内容并解析成 AST
        # errors="replace" 表示遇到编码错误时用替换字符代替（不中断）
        tree = ast.parse(filepath.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as e:
        logger.warning("Syntax error in %s: %s", filepath, e)
        return []

    blocks: list[dict] = []
    # 计算相对路径（用于存储到 ChromaDB 的元数据中）
    rel_path = filepath.relative_to(ROOT.parent if "backend" in str(filepath) else ROOT)
    # 读取源码行（用于提取代码块的文本内容）
    source_lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()

    # ast.walk 遍历 AST 中的所有节点（深度优先）
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 普通函数和异步函数
            start = node.lineno or 1
            end = node.end_lineno or start
            # 从源码中提取这个函数的完整代码（从起始行到结束行）
            content = "\n".join(source_lines[start - 1 : end])
            blocks.append(
                {
                    "name": node.name,  # 函数名
                    "kind": "function",  # 类型：函数
                    "file": str(rel_path),  # 相对文件路径
                    "start_line": start,  # 起始行号
                    "end_line": end,  # 结束行号
                    "content": content,  # 代码文本
                    "language": "python",  # 语言
                }
            )
        elif isinstance(node, ast.ClassDef):
            # 类定义
            start = node.lineno or 1
            end = node.end_lineno or start
            content = "\n".join(source_lines[start - 1 : end])
            blocks.append(
                {
                    "name": node.name,
                    "kind": "class",  # 类型：类
                    "file": str(rel_path),
                    "start_line": start,
                    "end_line": end,
                    "content": content,
                    "language": "python",
                }
            )

    return blocks


def _extract_java_blocks(filepath: Path) -> list[dict]:
    """从 Java 文件中提取类和方法（使用正则表达式）。

    为什么 Java 不用 AST？
        Java 的 AST 解析器（如 javaparser）需要 JVM 环境，
        为了简化依赖，这里用正则表达式做"够用"的提取。
        虽然不如 AST 精确，但对大多数标准格式的 Java 代码有效。

    参数:
        filepath: Java 文件路径

    返回:
        代码块列表
    """
    text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    blocks: list[dict] = []
    rel_path = filepath.relative_to(ROOT.parent)

    # 编译正则表达式（预编译提高效率）
    # 匹配类/接口/枚举声明，如 "public class UserService {"
    class_pat = re.compile(
        r"(?:public\s+)?(?:abstract\s+)?(?:class|interface|enum)\s+(\w+)"
    )
    # 匹配方法声明，如 "public void doSomething(String arg) {"
    method_pat = re.compile(
        r"(?:public|private|protected|static|final|abstract|synchronized|default|\s)*\s+"
        r"(?:<[^>]+>\s+)?"
        r"(\w+(?:\[\])*(?:<\w+>)?)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+\w+(?:\s*,\s*\w+)*)?\s*\{"
    )

    for i, line in enumerate(lines):
        # 先尝试匹配类声明
        cm = class_pat.search(line)
        if cm and "{" in line:
            block_end = _find_block_end(lines, i)
            content = "\n".join(lines[i : block_end + 1])
            blocks.append(
                {
                    "name": cm.group(1),  # 类名
                    "kind": "class",
                    "file": str(rel_path),
                    "start_line": i + 1,  # 行号从 1 开始
                    "end_line": block_end + 1,
                    "content": content,
                    "language": "java",
                }
            )
            continue  # 类声明行不再检查方法

        # 再尝试匹配方法声明
        mm = method_pat.search(line)
        if mm and "{" in line:
            block_end = _find_block_end(lines, i)
            content = "\n".join(lines[i : block_end + 1])
            blocks.append(
                {
                    "name": mm.group(2),  # 方法名（第2个捕获组）
                    "kind": "method",
                    "file": str(rel_path),
                    "start_line": i + 1,
                    "end_line": block_end + 1,
                    "content": content,
                    "language": "java",
                }
            )

    return blocks


def _extract_ts_blocks(filepath: Path) -> list[dict]:
    """从 TypeScript 文件中提取函数和类（使用正则表达式）。

    支持三种函数形式：
    1. 传统函数：function foo() {}
    2. 箭头函数：const foo = () => {}
    3. 类声明：class Foo {}

    参数:
        filepath: TypeScript 文件路径

    返回:
        代码块列表
    """
    text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    blocks: list[dict] = []
    rel_path = filepath.relative_to(ROOT.parent)

    # 匹配 function 声明
    func_pat = re.compile(
        r"(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)\s*=>|function))"
    )
    # 匹配 class 声明
    class_pat = re.compile(r"(?:export\s+)?(?:abstract\s+)?class\s+(\w+)")
    # 匹配箭头函数赋值：const X = ... =>
    arrow_pat = re.compile(r"const\s+(\w+)\s*[:=]\s*(?:[^=]|$)")

    for i, line in enumerate(lines):
        # 先检查类声明
        cm = class_pat.search(line)
        if cm and "{" in line:
            block_end = _find_block_end(lines, i)
            content = "\n".join(lines[i : block_end + 1])
            blocks.append(
                {
                    "name": cm.group(1),
                    "kind": "class",
                    "file": str(rel_path),
                    "start_line": i + 1,
                    "end_line": block_end + 1,
                    "content": content,
                    "language": "typescript",
                }
            )
            continue

        # 再检查 function 声明
        fm = func_pat.search(line)
        if fm:
            name = fm.group(1) or fm.group(2)  # 取匹配到的函数名
            block_end = _find_block_end(lines, i)
            content = "\n".join(lines[i : block_end + 1]) if block_end > i else line
            blocks.append(
                {
                    "name": name,
                    "kind": "function",
                    "file": str(rel_path),
                    "start_line": i + 1,
                    "end_line": block_end + 1,
                    "content": content,
                    "language": "typescript",
                }
            )
            continue

        # 最后检查箭头函数
        am = arrow_pat.search(line)
        if am and "=>" in line:
            block_end = _find_block_end(lines, i)
            content = "\n".join(lines[i : block_end + 1]) if block_end > i else line
            blocks.append(
                {
                    "name": am.group(1),
                    "kind": "function",
                    "file": str(rel_path),
                    "start_line": i + 1,
                    "end_line": block_end + 1,
                    "content": content,
                    "language": "typescript",
                }
            )

    return blocks


def _find_block_end(lines: list[str], start: int, max_lookahead: int = 200) -> int:
    """通过花括号计数找到代码块的结束位置。

    原理：
        Java/TypeScript 用 {} 包围代码块。
        从起始行开始，遇到 { 深度+1，遇到 } 深度-1。
        当深度回到 0 时，说明找到了匹配的 }。

    参数:
        lines: 所有源码行
        start: 代码块起始行索引
        max_lookahead: 最大向前查找行数（防止无限循环）

    返回:
        代码块结束行的索引。如果找不到则返回 start。
    """
    depth = 0
    for i in range(start, min(start + max_lookahead, len(lines))):
        # 统计当前行中 { 和 } 的数量差
        depth += lines[i].count("{") - lines[i].count("}")
        # 深度回到 0 且不是起始行 → 找到了闭合的 }
        if depth <= 0 and i > start:
            return i
    return start


# ============================================================
# 主流程
# ============================================================


def collect_code_blocks() -> list[dict]:
    """扫描所有代码根目录，提取代码块。

    返回:
        所有提取到的代码块列表
    """
    total_blocks = 0
    all_blocks: list[dict] = []

    for lang, code_root in CODE_ROOTS:
        if not code_root.exists():
            logger.info("Skipping (not found): %s", code_root)
            continue

        # 根据语言选择对应的提取器和文件扩展名
        if lang == "python":
            files = list(code_root.rglob("*.py"))  # rglob 递归搜索
            extractor = _extract_python_blocks
        elif lang == "java":
            files = list(code_root.rglob("*.java"))
            extractor = _extract_java_blocks
        elif lang == "typescript":
            files = list(code_root.rglob("*.ts")) + list(code_root.rglob("*.tsx"))
            extractor = _extract_ts_blocks
        else:
            continue

        # 排除测试文件（让索引更干净，避免检索时返回测试代码）
        test_files = {f for f in files if "test" in f.name.lower() or "Test" in f.name}
        files = [f for f in files if f not in test_files]

        for filepath in sorted(files):
            try:
                blocks = extractor(filepath)
                for b in blocks:
                    # 跳过太小的代码块（getter/setter/简单 lambda 等，通常只有1-2行）
                    if b["end_line"] - b["start_line"] < 2:
                        continue
                all_blocks.extend(blocks)
                total_blocks += len(blocks)
            except Exception as e:
                logger.debug("Error processing %s: %s", filepath, e)

    logger.info("Collected %d code blocks from %d roots", total_blocks, len(CODE_ROOTS))
    return all_blocks


def index_codebase(settings: AppSettings | None = None) -> None:
    """主入口：扫描代码库 → 生成嵌入 → 存入 ChromaDB。

    参数:
        settings: 应用配置（可选）
    """
    settings = settings or AppSettings()
    # 代码块的集合名 = 事故集合名 + "_code_blocks"
    collection_name = f"{settings.chroma_collection}_code_blocks"

    # 第 1 步：提取所有代码块
    blocks = collect_code_blocks()
    if not blocks:
        logger.warning("No code blocks found.")
        return

    logger.info("Generating embeddings for %d code blocks...", len(blocks))

    # 第 2 步：获取/创建 ChromaDB 集合
    client = get_chroma_client(settings)
    collection = client.get_or_create_collection(
        name=collection_name,
        # 使用余弦相似度（cosine）作为向量距离度量
        # 余弦相似度衡量两个向量的"方向"是否一致，值域 [-1, 1]，越大越相似
        configuration={"hnsw": {"space": "cosine"}},
        # embedding_function=None 表示我们自己管理嵌入（手动传入向量）
        embedding_function=None,
    )

    # 准备批量数据
    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, Any]] = []

    for i, block in enumerate(blocks):
        doc_text = block["content"]
        # 生成唯一 ID：文件路径:类型:名称:行号
        # 例如 "backend/src/main/java/com/acme/UserService.java:class:UserService:L10"
        block_id = (
            f"{block['file']}:{block['kind']}:{block['name']}:L{block['start_line']}"
        )

        try:
            # 调用嵌入模型把代码文本转成向量
            embedding = _fetch_query_embedding(doc_text, settings=settings)
        except Exception as e:
            logger.warning("Embedding failed for %s: %s", block_id, e)
            continue  # 跳过嵌入失败的代码块

        ids.append(block_id)
        documents.append(doc_text)
        embeddings.append(embedding)
        metadatas.append(
            {
                "name": block["name"],
                "kind": block["kind"],
                "file": block["file"],
                "start_line": block["start_line"],
                "end_line": block["end_line"],
                "language": block["language"],
            }
        )

    if not ids:
        logger.warning("No blocks produced embeddings.")
        return

    # 第 3 步：分批 upsert 到 ChromaDB（每批 100 条，避免请求过大）
    batch_size = 100
    for batch_start in range(0, len(ids), batch_size):
        batch_end = batch_start + batch_size
        collection.upsert(
            ids=ids[batch_start:batch_end],
            documents=documents[batch_start:batch_end],
            embeddings=embeddings[batch_start:batch_end],
            metadatas=metadatas[batch_start:batch_end],
        )
        logger.info(
            "Indexed batch %d/%d (%d blocks)",
            batch_start // batch_size + 1,
            (len(ids) + batch_size - 1) // batch_size,
            batch_end - batch_start,
        )

    logger.info(
        "Done. Indexed %d code blocks into Chroma collection '%s'",
        len(ids),
        collection_name,
    )

    # 打印统计信息
    by_lang: dict[str, int] = {}  # 按语言统计
    by_kind: dict[str, int] = {}  # 按类型统计（class/function/method）
    for m in metadatas:
        by_lang[m["language"]] = by_lang.get(m["language"], 0) + 1
        by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1

    logger.info("By language: %s", json.dumps(by_lang, ensure_ascii=False))
    logger.info("By kind: %s", json.dumps(by_kind, ensure_ascii=False))
    logger.info("Collection: %s", collection_name)


if __name__ == "__main__":
    index_codebase()
