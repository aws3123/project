"""代码差异提取器 —— 从 diff 中提取完整的方法体。

本模块负责从 unified diff（统一差异格式）中智能提取完整的代码方法体，
而不是简单地截取变更行。这样 LLM 在审查时能看到完整的方法上下文，
做出更准确的判断。

核心概念：
  - unified diff：代码差异的标准格式，用 @@ 标记"块"（hunk），+ 表示新增行，- 表示删除行
  - 方法体提取：从 diff 中找到方法签名，然后追踪到方法结束（花括号闭合/缩进恢复），
    提取出完整的方法代码

为什么需要方法级提取？
  - 简单截取变更行 → LLM 只看到几行代码，缺乏上下文，容易误判
  - 方法级提取 → LLM 看到完整方法，理解调用关系，判断更准确

支持的语言：
  - Java/JS/TS：用花括号 {} 追踪方法边界
  - Python：用缩进追踪方法边界

类比：
  就像从报纸剪报——不是只剪下修改的那句话，而是把整个段落都剪下来，
  这样读者才能理解完整语境。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 各语言的方法签名正则模式（用于识别"这是一行方法定义"）
_METHOD_PATTERNS: dict[str, list[str]] = {
    "java": [
        # public/private/protected [static] [final] returnType methodName(
        r"(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?"
        r"(?:[\w<>\[\]?,\s]+)\s+\w+\s*\(",
        # 构造函数: ClassName(
        r"(?:public|private|protected)\s+\w+\s*\(",
    ],
    "python": [
        r"(?:async\s+)?def\s+\w+\s*\(",
    ],
    "javascript": [
        r"(?:async\s+)?(?:function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\(?[^)]*\)?\s*=>)",
    ],
    "typescript": [
        r"(?:async\s+)?(?:function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\(?[^)]*\)?\s*=>)",
    ],
}

# 通用后备模式：用于未知语言的兜底方法签名检测
_GENERIC_METHOD_PATTERN = re.compile(
    r"(?:(?:public|private|protected|static|final|async|def|function|const|let|var)\s+)+"
    r"\w+\s*[\(<]"
)


def _detect_language(path: str) -> str:
    """根据文件扩展名检测编程语言。"""
    ext_map = {
        ".java": "java", ".py": "python", ".js": "javascript",
        ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return "unknown"


def _is_method_signature(stripped_line: str, language: str) -> bool:
    """判断去掉 diff 前缀后的行是否匹配方法签名模式。"""
    patterns = _METHOD_PATTERNS.get(language, [])
    for pattern in patterns:
        if re.search(pattern, stripped_line):
            return True
    # Generic fallback for unknown languages
    if language == "unknown" and _GENERIC_METHOD_PATTERN.search(stripped_line):
        return True
    return False


def _strip_diff_prefix(line: str) -> str:
    """去掉行首的 diff 标记（+/-/空格），返回原始代码。"""
    if line and len(line) > 0 and line[0] in ("+", "-", " "):
        return line[1:]
    return line


def _extract_methods_from_hunk(
    hunk_lines: list[str],
    language: str,
    max_chars: int,
) -> tuple[list[str], list[str]]:
    """从 diff hunk（代码块）中提取完整的方法体。

    根据语言选择不同的提取策略：
    - Python：用缩进级别判断方法边界
    - Java/JS/TS：用花括号深度判断方法边界

    参数:
        hunk_lines: 单个 @@ 块中的所有行（不含 @@ 头）
        language:   检测到的编程语言
        max_chars:  最大提取字符数

    返回:
        (提取的代码行列表, 方法名列表)
    """
    if language == "python":
        return _extract_methods_python(hunk_lines, max_chars)
    return _extract_methods_brace(hunk_lines, language, max_chars)


def _extract_methods_python(
    hunk_lines: list[str],
    max_chars: int,
) -> tuple[list[str], list[str]]:
    """Python 专用提取：用缩进检测方法边界。"""
    extracted: list[str] = []
    method_names: list[str] = []
    total_chars = 0
    in_method = False
    method_indent = 0
    current_method = ""

    for line in hunk_lines:
        stripped = _strip_diff_prefix(line)
        stripped_clean = stripped.strip()

        if not in_method:
            if _is_method_signature(stripped_clean, "python"):
                in_method = True
                # Measure indentation of the def line
                method_indent = len(stripped) - len(stripped.lstrip())
                current_method = line + "\n"
                method_names.append(stripped_clean[:60])
            continue
        else:
            # Inside a Python method
            if not stripped_clean:
                # Blank line — keep accumulating (may be between methods)
                current_method += line + "\n"
                continue

            line_indent = len(stripped) - len(stripped.lstrip())
            if line_indent <= method_indent:
                # New statement at same or lower indent — method ended
                extracted.append(current_method.rstrip("\n"))
                total_chars += len(current_method)
                current_method = ""
                in_method = False
                if total_chars >= max_chars:
                    break
                # Check if this line starts a new method
                if _is_method_signature(stripped_clean, "python"):
                    in_method = True
                    method_indent = line_indent
                    current_method = line + "\n"
                    method_names.append(stripped_clean[:60])
            else:
                current_method += line + "\n"

    # Handle truncated method (hunk ends before method closes)
    if in_method and current_method:
        extracted.append(current_method.rstrip("\n"))
        total_chars += len(current_method)

    return extracted, method_names


def _extract_methods_brace(
    hunk_lines: list[str],
    language: str,
    max_chars: int,
) -> tuple[list[str], list[str]]:
    """花括号语言（Java/JS/TS）专用提取：用花括号深度检测方法边界。"""
    extracted: list[str] = []
    method_names: list[str] = []
    total_chars = 0
    in_method = False
    brace_depth = 0
    current_method = ""

    for line in hunk_lines:
        stripped = _strip_diff_prefix(line)
        stripped_clean = stripped.strip()

        if not in_method:
            if _is_method_signature(stripped_clean, language):
                in_method = True
                brace_depth = 0
                current_method = line + "\n"
                method_names.append(stripped_clean[:60])

                brace_depth += stripped.count("{") - stripped.count("}")
                if brace_depth <= 0 and "{" in stripped:
                    extracted.append(current_method.rstrip("\n"))
                    total_chars += len(current_method)
                    current_method = ""
                    in_method = False
                    if total_chars >= max_chars:
                        break
                continue

            if "{" in stripped_clean:
                brace_depth += stripped.count("{") - stripped.count("}")
        else:
            current_method += line + "\n"
            brace_depth += stripped.count("{") - stripped.count("}")

            if brace_depth <= 0:
                extracted.append(current_method.rstrip("\n"))
                total_chars += len(current_method)
                current_method = ""
                in_method = False
                if total_chars >= max_chars:
                    break

    if in_method and current_method:
        extracted.append(current_method.rstrip("\n") + "\n... (方法截断)")
        total_chars += len(current_method)

    return extracted, method_names


def extract_complete_methods(
    file_path: str,
    diff: str,
    max_chars: int = 2000,
) -> tuple[str, list[str]]:
    """从 unified diff 中提取完整的方法体。

    解析 diff 中的 hunk（@@ 块），在每个块中识别方法签名并提取完整方法体
    （从签名到闭合花括号/缩进恢复）。这样 LLM 能看到完整方法而非截断的代码行。

    参数:
        file_path: 文件路径（用于语言检测）
        diff:      unified diff 内容
        max_chars: 所有方法的最大提取字符数

    返回:
        (snippet, method_names) - 格式化的代码片段和检测到的方法名列表
    """
    language = _detect_language(file_path)
    all_methods: list[str] = []
    all_names: list[str] = []
    total_chars = 0

    # 将 diff 按 @@ 分割成多个 hunk（代码块）
    hunk_pattern = re.compile(r"^@@\s+[^@]+@@.*$", re.MULTILINE)
    hunk_starts = [m.end() for m in hunk_pattern.finditer(diff)]

    if not hunk_starts:
        # 没有找到 unified diff 的 hunk → 降级为简单的新增行提取
        return _fallback_extract(diff, max_chars), []

    # 逐个处理 hunk
    prev_end = 0
    for i, start in enumerate(hunk_starts):
        if total_chars >= max_chars:
            break
        end = hunk_starts[i + 1] if i + 1 < len(hunk_starts) else len(diff)
        hunk_text = diff[prev_end:end] if i == 0 else diff[start:end]
        hunk_lines = hunk_text.splitlines()

        # 去掉 hunk 中的 @@ 头行
        if hunk_lines and hunk_lines[0].startswith("@@"):
            hunk_lines = hunk_lines[1:]

        methods, names = _extract_methods_from_hunk(
            hunk_lines, language, max_chars - total_chars,
        )
        all_methods.extend(methods)
        all_names.extend(names)
        total_chars += sum(len(m) for m in methods)

    if not all_methods:
        # 没有检测到方法 → 降级为简单提取
        return _fallback_extract(diff, max_chars), []

    return "\n".join(all_methods)[:max_chars], all_names


def _fallback_extract(diff: str, max_chars: int = 2000) -> str:
    """降级提取：当检测不到方法时，简单提取所有新增行。

    这是原始行为：提取以 "+" 开头的行并截断。
    """
    added = [
        line for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    result = "\n".join(added)
    return result[:max_chars]


def _sort_files_by_impact(
    files: list[dict],
    impact_radius: dict | None = None,
    code_graph: dict | None = None,
) -> list[dict]:
    """按影响范围分数对文件排序，影响大的文件优先。

    为什么要排序？
        当 diff 涉及多个文件时，LLM 上下文窗口有限（max_files=5），
        如果直接取前 N 个，可能漏掉高风险文件。
        通过 impact_radius 的影响分数排序，确保影响范围最大的文件优先进入 LLM 审查。

    排序逻辑：
        1. 从 code_graph 构建 node_id → file_path 映射
        2. 从 impact_radius["affected"] 聚合每个文件的影响分数
           （changed 节点本身也在 affected 列表中，且分数最高）
        3. 按文件影响分数降序排序
        4. 没有影响数据的文件排在最后，保持原始顺序

    参数:
        files:         原始文件列表
        impact_radius: impact 节点输出，含 affected 列表
        code_graph:    code_knowledge_graph 输出，含 nodes 列表

    返回:
        排序后的文件列表（不影响原始列表）
    """
    if not impact_radius or not code_graph:
        return files  # 没有影响数据，保持原始顺序

    # 构建 node_id → file_path 映射
    node_to_file: dict[str, str] = {}
    for node in code_graph.get("nodes", []):
        node_id = node.get("id", "")
        file_path = node.get("file", "")
        if node_id and file_path:
            node_to_file[node_id] = file_path

    # 聚合每个文件的影响分数
    file_scores: dict[str, float] = {}
    for item in impact_radius.get("affected", []):
        node_id = item.get("node", "")
        score = item.get("score", 0.0)
        file_path = node_to_file.get(node_id, "")
        if file_path:
            file_scores[file_path] = file_scores.get(file_path, 0.0) + score

    if not file_scores:
        return files  # 无法映射到文件，保持原始顺序

    # 按影响分数降序排序；无分数的文件保持原始相对顺序（stable sort）
    return sorted(files, key=lambda f: -file_scores.get(f.get("path", ""), 0.0))


def build_diff_snippet(
    files: list[dict],
    max_files: int = 5,
    max_chars_per_file: int = 2000,
    max_chars_total: int = 6000,
    impact_radius: dict | None = None,
    code_graph: dict | None = None,
) -> tuple[str, list[str]]:
    """构建方法级 diff 代码片段。

    遍历文件列表，从每个文件中提取完整方法体，并加上文件路径头。
    这是安全审计（security.py）和性能分析（performance.py）节点的核心依赖。

    如果传入 impact_radius 和 code_graph，会先按影响范围分数排序文件，
    确保高风险文件优先进入 LLM 上下文。

    参数:
        files:            文件字典列表，每个含 'path' 和 'diff' 键
        max_files:        最多处理的文件数
        max_chars_per_file: 每个文件的最大字符数
        max_chars_total:  所有文件的总最大字符数
        impact_radius:    impact 节点输出（可选），用于文件优先级排序
        code_graph:       code_knowledge_graph 输出（可选），提供 node→file 映射

    返回:
        (代码片段, 所有方法名列表)
    """
    # 按影响范围排序，高风险文件优先
    sorted_files = _sort_files_by_impact(files, impact_radius, code_graph)

    parts: list[str] = []
    all_names: list[str] = []
    total_chars = 0

    for f in sorted_files[:max_files]:
        if total_chars >= max_chars_total:
            break
        path = f.get("path", "")
        diff = f.get("diff", "")
        if not diff:
            continue

        snippet, names = extract_complete_methods(
            path, diff, max_chars=max_chars_per_file,
        )
        if snippet:
            parts.append(f"--- {path} ---\n{snippet}")
            all_names.extend(names)
            total_chars += len(snippet)

    return "\n\n".join(parts), all_names
