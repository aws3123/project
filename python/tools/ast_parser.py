"""
AST 解析工具
========================

作用：
    解析代码的抽象语法树（AST），提取代码结构信息（类、方法、字段等）。
    这些信息用于构建代码知识图谱、分析变更影响范围。

什么是 AST？
    AST（Abstract Syntax Tree，抽象语法树）是代码结构的树形表示。
    例如：`class Foo { void bar() {} }` 会被解析为：
        ClassDef(Foo)
          └── MethodDef(bar)
    通过 AST，我们可以知道代码里有哪些类、方法、它们在哪里。

什么是 Tree-sitter？
    Tree-sitter 是一个高性能的增量解析库，支持多种编程语言。
    比 Python 内置的 ast 模块更强大，支持 Java、SQL 等语言。

检查逻辑：
    1. 如果 Java BFF 已经预处理了实体/关系，直接使用（性能优化）
    2. 否则，根据文件语言选择解析器（Python 用 ast，Java 用 tree-sitter/javalang）
    3. 提取代码实体（类、方法等）和它们之间的关系（调用、继承等）
"""

# annotations 延迟求值
from __future__ import annotations

# ast 是 Python 内置的 AST 解析模块
import ast as py_ast

# logging 记录日志
import logging

# re 正则表达式模块
import re

# Callable 表示可调用类型
# dataclass 自动生成构造方法等
from dataclasses import dataclass, field

# wraps 保留被装饰函数的元信息
from functools import wraps

# 导入工具基础类型
from tools.base import Tool, ToolContext, ToolResult

# 创建当前模块的日志记录器
logger = logging.getLogger(__name__)

# 单次请求最大解析文件数（防止恶意提交大量文件导致性能问题）
MAX_FILES_PER_REQUEST = 50

# TARGET_NODE_TYPES: 每种语言需要提取的 AST 节点类型
# 键是语言名，值是 {节点类型: 实体类别} 的映射
TARGET_NODE_TYPES = {
    "python": {
        "ClassDef": "class",
        "FunctionDef": "method",
        "AsyncFunctionDef": "method",
        "Import": "import",
        "ImportFrom": "import",
    },
    "java": {
        "class_declaration": "class",
        "method_declaration": "method",
        "field_declaration": "field",
        "import_declaration": "import",
        "interface_declaration": "interface",
    },
    "sql": {
        "create_table": "table",
        "alter_table": "table",
        "drop_table": "table",
        "create_index": "index",
    },
}

# 检查 tree-sitter 是否可用（可选依赖）
TREE_SITTER_AVAILABLE = False
try:
    import tree_sitter

    TREE_SITTER_AVAILABLE = True
except ImportError:
    pass

# 检查 javalang 是否可用（可选依赖，用于解析 Java 代码）
JAVALANG_AVAILABLE = False
try:
    import javalang

    JAVALANG_AVAILABLE = True
except ImportError:
    pass


# =============================================================================
# 代码实体 —— 表示代码中的一个结构元素（类、方法、字段等）
# =============================================================================
@dataclass
class CodeEntity:
    """代码实体 —— 表示代码中的一个结构元素。

    属性：
        name: 实体名称（如类名、方法名）
        kind: 实体类型（class/method/field/import）
        file_path: 所在文件路径
        line_start: 起始行号
        line_end: 结束行号（可选）
        language: 编程语言
        modifiers: 修饰符列表（如 ["public", "static"]）
        signature: 方法/类签名
        fully_qualified_name: 全限定名（如 com.example.UserService）
        parent_class: 父类名（如果是类成员）
        package: 包名
    """

    name: str
    kind: str
    file_path: str
    line_start: int
    line_end: int = 0
    language: str = ""
    modifiers: list[str] = field(default_factory=list)
    signature: str = ""
    fully_qualified_name: str = ""
    parent_class: str = ""
    package: str = ""


# =============================================================================
# 代码关系 —— 表示两个实体之间的关系
# =============================================================================
@dataclass
class CodeRelation:
    """代码关系 —— 表示两个实体之间的关系。

    属性：
        source: 源实体（调用方）
        target: 目标实体（被调用方）
        relation_type: 关系类型（CALLS/EXTENDS/IMPLEMENTS/IMPORTS/REFERENCES）
    """

    source: str
    target: str
    relation_type: str  # CALLS / EXTENDS / IMPLEMENTS / IMPORTS / REFERENCES


# =============================================================================
# 超时装饰器 —— 限制函数执行时间
# =============================================================================
def timeout(seconds: int):
    """超时装饰器 —— 限制函数执行时间。

    如果函数执行超过指定秒数，会触发超时异常。
    注意：这个装饰器只在 Unix 系统上有效（使用 signal.alarm）。
    """
    import signal as _signal

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                _signal.alarm(seconds)  # 设置闹钟
                return func(*args, **kwargs)
            finally:
                _signal.alarm(0)  # 取消闹钟

        return wrapper

    return decorator


class ASTParserTool(Tool):
    """AST 解析工具 —— 解析代码的抽象语法树，提取结构信息。"""

    # 工具的唯一标识符
    name = "ast_parser"
    description = (
        "解析代码片段或文件列表的抽象语法树，提取类/方法/字段等实体及调用关系。"
        "入参 files(含 path/diff/full_content) 或 code+language；返回实体与关系。"
    )
    parameters = {
        "files": "list[dict]，每个含 path、diff、full_content",
        "code": "str，可选单段源码；language: python/java/sql",
    }

    def run(self, payload: dict, context: ToolContext | None = None) -> ToolResult:
        """执行 AST 解析。

        参数 payload：
            - files: 文件列表，每个文件包含 path、diff、full_content
            - entities/relations: 可选的预处理结果（来自 Java BFF）

        返回：
            ToolResult，包含实体列表和关系列表
        """
        # 快捷路径：如果 Java BFF 已经预处理了实体/关系，直接使用（跳过本地解析）
        pre_entities = payload.get("entities")
        pre_relations = payload.get("relations")
        if pre_entities is not None and pre_relations is not None:
            logger.info(
                "Using preprocessed entities/relations from Java BFF, skipping local AST parsing"
            )
            return ToolResult(
                name=self.name,
                payload={
                    "entities": pre_entities,
                    "relations": pre_relations,
                },
            )

        files = payload.get("files", [])
        # 限制文件数量，防止恶意提交
        if len(files) > MAX_FILES_PER_REQUEST:
            logger.warning(
                "Too many files (%d), limiting to %d", len(files), MAX_FILES_PER_REQUEST
            )
            files = files[:MAX_FILES_PER_REQUEST]

        entities: list[CodeEntity] = []  # 存放所有代码实体
        relations: list[CodeRelation] = []  # 存放所有代码关系

        # 遍历每个文件进行解析
        for f in files:
            path = f.get("path", "")
            diff = f.get("diff", "")
            full_content = f.get("full_content", "")
            lang = self._detect_language(path)  # 检测文件语言

            try:
                file_entities = self._extract_entities(path, diff, full_content, lang)
                entities.extend(file_entities)
                file_relations = self._extract_relations(file_entities, diff, lang)
                relations.extend(file_relations)
            except Exception as e:
                logger.warning("AST parse failed for %s: %s", path, e)

        # 返回解析结果（转换为字典格式）
        return ToolResult(
            name=self.name,
            payload={
                "entities": [self._entity_to_dict(e) for e in entities],
                "relations": [self._relation_to_dict(r) for r in relations],
            },
        )

    def _detect_language(self, path: str) -> str:
        """根据文件扩展名检测编程语言。"""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        lang_map = {
            "java": "java",
            "py": "python",
            "sql": "sql",
            "yml": "yaml",
            "yaml": "yaml",
            "xml": "xml",
            "properties": "properties",
            "json": "json",
        }
        return lang_map.get(ext, "unknown")

    def _extract_entities(
        self, path: str, diff: str, full_content: str, lang: str
    ) -> list[CodeEntity]:
        """从文件中提取代码实体。根据语言选择不同的解析器。"""
        changed_ranges = self._diff_line_ranges(diff)  # 获取变更的行号范围

        if lang == "python":
            return self._parse_python(path, diff, full_content, changed_ranges)
        elif lang == "java":
            return self._parse_java(path, diff, full_content, changed_ranges)
        elif lang == "sql":
            return self._parse_sql(path, diff, changed_ranges)
        else:
            return self._parse_generic(path, diff, lang)

    def _diff_line_ranges(self, diff: str) -> set[int]:
        """从 diff 中提取变更的行号范围。

        解析 unified diff 的 @@ 头部，获取新增/修改的行号。
        例如：@@ -1,3 +1,5 @@ 表示新文件从第 1 行开始，共 5 行。
        """
        ranges: set[int] = set()
        # 解析 @@ 头部获取变更行号
        for m in re.finditer(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff):
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) else 1
            for i in range(start, start + count):
                ranges.add(i)
        # 如果没有 @@ 头部，尝试解析 + 开头的行（新文件的情况）
        if not ranges:
            line_num = 0
            for line in diff.splitlines():
                line_num += 1
                if line.startswith("+") and not line.startswith("+++"):
                    ranges.add(line_num)
        return ranges

    def _parse_python(
        self, path: str, diff: str, full_content: str, changed_ranges: set[int]
    ) -> list[CodeEntity]:
        """解析 Python 代码，提取类、函数、导入等实体。"""
        entities: list[CodeEntity] = []
        # 如果有完整内容就用完整内容，否则从 diff 重建
        source = full_content or self._reconstruct_python(diff)
        if not source.strip():
            return entities
        try:
            tree = py_ast.parse(source)  # 解析 Python 源码为 AST
            package = self._extract_python_package(source)  # 提取包名
            for node in py_ast.walk(tree):
                if node.__class__.__name__ not in TARGET_NODE_TYPES["python"]:
                    continue
                start_line = getattr(node, "lineno", 0)
                # 只关注变更范围内的实体
                if changed_ranges and start_line not in changed_ranges:
                    continue
                entity = self._py_node_to_entity(node, path, package, source)
                if entity:
                    entities.append(entity)
        except SyntaxError as e:
            logger.debug(
                "Python syntax error in %s: %s (falling back to regex)", path, e
            )
            entities = self._parse_generic(path, diff, "python")
        return entities

    def _reconstruct_python(self, diff: str) -> str:
        """从 diff 重建 Python 源码（提取 + 开头的行）。"""
        lines = []
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:])  # 去掉 + 号
            elif (
                not line.startswith("-")
                and not line.startswith("---")
                and not line.startswith("@@")
            ):
                lines.append(line)  # 保留未变更的行
        return "\n".join(lines)

    def _extract_python_package(self, source: str) -> str:
        """从 Python 源码中提取包名（从 import 语句推断）。"""
        for line in source.splitlines()[:10]:
            m = re.match(r"^from\s+([\w.]+)\s+import", line)
            if m:
                return m.group(1)
        return ""

    def _py_node_to_entity(
        self, node, path: str, package: str, source: str
    ) -> CodeEntity | None:
        """将 Python AST 节点转换为 CodeEntity。"""
        kind_map = {
            "ClassDef": "class",
            "FunctionDef": "method",
            "AsyncFunctionDef": "method",
            "Import": "import",
            "ImportFrom": "import",
        }
        kind = kind_map.get(node.__class__.__name__, "unknown")
        name = getattr(node, "name", "unknown")
        start = getattr(node, "lineno", 0)
        end = (
            getattr(node, "end_lineno", start) if hasattr(node, "end_lineno") else start
        )

        qname = f"{path}::{name}"
        if package:
            qname = f"{package}.{name}"

        # 查找父类（如果是类成员）
        parent_class = ""
        for n in py_ast.walk(node):
            if isinstance(n, py_ast.ClassDef) and n != node:
                parent_class = n.name
                qname = (
                    f"{package}.{parent_class}.{name}"
                    if package
                    else f"{parent_class}.{name}"
                )
                break

        return CodeEntity(
            name=name,
            kind=kind,
            file_path=path,
            line_start=start,
            line_end=end,
            language="python",
            fully_qualified_name=qname,
            parent_class=parent_class,
            package=package,
            signature=self._py_get_signature(node, source),
        )

    def _py_get_signature(self, node, source: str) -> str:
        """获取 Python 节点的源代码片段作为签名。"""
        try:
            return py_ast.get_source_segment(source, node) or ""
        except Exception:
            return ""

    def _parse_java(
        self, path: str, diff: str, full_content: str, changed_ranges: set[int]
    ) -> list[CodeEntity]:
        """解析 Java 代码，提取类、方法、字段等实体。"""
        entities: list[CodeEntity] = []
        source = full_content or self._reconstruct_generic(diff, "+")

        # 优先使用 javalang 库解析
        if JAVALANG_AVAILABLE and source.strip():
            try:
                tree = javalang.parse.parse(source)
                package = tree.package.name if tree.package else ""
                if tree.types:
                    for t in tree.types:
                        entities.extend(
                            self._javalang_type_to_entities(
                                t, path, package, changed_ranges, source
                            )
                        )
                return entities
            except Exception as e:
                logger.debug("javalang parse failed for %s: %s", path, e)

        # 如果 javalang 不可用或解析失败，回退到正则表达式解析
        return self._parse_generic(path, diff, "java")

    def _javalang_type_to_entities(
        self, type_decl, path: str, package: str, changed_ranges: set[int], source: str
    ) -> list[CodeEntity]:
        """将 javalang 解析的类型声明转换为 CodeEntity 列表。"""
        entities: list[CodeEntity] = []
        class_name = type_decl.name
        fqn = f"{package}.{class_name}" if package else class_name

        for member in getattr(type_decl, "body", []):
            if isinstance(member, javalang.tree.MethodDeclaration):
                name = member.name
                line = getattr(member, "_position", None)
                line_num = line.line if line else 0
                if changed_ranges and line_num not in changed_ranges:
                    continue
                method_fqn = f"{fqn}::{name}"
                entities.append(
                    CodeEntity(
                        name=name,
                        kind="method",
                        file_path=path,
                        line_start=line_num,
                        language="java",
                        fully_qualified_name=method_fqn,
                        parent_class=class_name,
                        package=package,
                        modifiers=member.modifiers or [],
                        signature=(
                            f"{member.return_type or 'void'} {name}(...)"
                            if member.return_type
                            else f"{name}(...)"
                        ),
                    )
                )
            elif isinstance(member, javalang.tree.FieldDeclaration):
                line = getattr(member, "_position", None)
                line_num = line.line if line else 0
                if changed_ranges and line_num not in changed_ranges:
                    continue
                for decl in member.declarators:
                    entities.append(
                        CodeEntity(
                            name=decl.name,
                            kind="field",
                            file_path=path,
                            line_start=line_num,
                            language="java",
                            fully_qualified_name=f"{fqn}.{decl.name}",
                            parent_class=class_name,
                            package=package,
                        )
                    )
        return entities

    def _parse_sql(
        self, path: str, diff: str, changed_ranges: set[int]
    ) -> list[CodeEntity]:
        """解析 SQL 代码，提取表、索引等实体。"""
        entities: list[CodeEntity] = []
        # SQL 关键字正则表达式映射
        sql_keywords = {
            r"(?i)CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)": "table",
            r"(?i)ALTER\s+TABLE\s+(\w+)": "table",
            r"(?i)DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)": "table",
            r"(?i)CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)": "index",
        }
        line_num = 0
        for line in diff.splitlines():
            line_num += 1
            if not line.startswith("+") or line.startswith("+++"):
                continue
            if changed_ranges and line_num not in changed_ranges:
                continue
            content = line[1:].strip()
            for pattern, kind in sql_keywords.items():
                m = re.search(pattern, content)
                if m:
                    entities.append(
                        CodeEntity(
                            name=m.group(1),
                            kind=kind,
                            file_path=path,
                            line_start=line_num,
                            language="sql",
                            fully_qualified_name=f"{path}::{m.group(1)}",
                            signature=content[:120],
                        )
                    )
        return entities

    def _parse_generic(self, path: str, diff: str, lang: str) -> list[CodeEntity]:
        """通用解析器（回退方案）—— 使用正则表达式提取代码结构。"""
        entities: list[CodeEntity] = []
        # 每种语言的正则表达式模式
        generic_patterns = {
            "java": [
                (
                    r"(?:public|private|protected)?\s*(?:static)?\s*(?:final)?\s*\w+\s+(\w+)\s*\(",
                    "method",
                ),
                (r"(?:public|private|protected)?\s*class\s+(\w+)", "class"),
                (r"import\s+([\w.]+)", "import"),
            ],
            "python": [
                (r"def\s+(\w+)\s*\(", "method"),
                (r"class\s+(\w+)", "class"),
                (r"(?:from\s+([\w.]+)\s+)?import\s+([\w.,\s]+)", "import"),
            ],
        }
        patterns = generic_patterns.get(lang, [])
        line_num = 0
        for line in diff.splitlines():
            line_num += 1
            if not line.startswith("+") or line.startswith("+++"):
                continue
            content = line[1:].strip()
            for pattern, kind in patterns:
                m = re.match(pattern, content)
                if m:
                    entities.append(
                        CodeEntity(
                            name=m.group(1),
                            kind=kind,
                            file_path=path,
                            line_start=line_num,
                            language=lang,
                            fully_qualified_name=f"{path}::{m.group(1)}",
                        )
                    )
        return entities

    def _reconstruct_generic(self, diff: str, prefix: str) -> str:
        """从 diff 重建源码（通用方法）。"""
        lines = []
        for line in diff.splitlines():
            if line.startswith(prefix) and not line.startswith(prefix * 3):
                lines.append(line[len(prefix) :])
            elif (
                not line.startswith("-")
                and not line.startswith("---")
                and not line.startswith("@@")
            ):
                lines.append(line)
        return "\n".join(lines)

    def _extract_relations(
        self, entities: list[CodeEntity], diff: str, lang: str
    ) -> list[CodeRelation]:
        """从 diff 中提取代码实体之间的关系（调用、继承等）。"""
        relations: list[CodeRelation] = []
        qnames = {e.fully_qualified_name for e in entities}

        for line in diff.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            content = line[1:].strip()

            # 提取方法调用：obj.method() 或 method()
            for m in re.finditer(r"(?:\w+\.)?(\w+)\s*\(", content):
                called = m.group(1)
                for e in entities:
                    if e.kind in ("method",) and called == e.name:
                        source_entity = self._find_enclosing_entity(
                            entities, e.line_start
                        )
                        if source_entity:
                            relations.append(
                                CodeRelation(
                                    source=source_entity.fully_qualified_name,
                                    target=e.fully_qualified_name,
                                    relation_type="CALLS",
                                )
                            )

            # 提取继承关系：extends ClassName
            extends_m = re.match(r".*extends\s+(\w+)", content)
            if extends_m:
                for e in entities:
                    if e.name == extends_m.group(1) and e.kind == "class":
                        for src in entities:
                            if (
                                src.kind == "class"
                                and src.line_start
                                == self._find_line_in_diff(diff, content)
                            ):
                                relations.append(
                                    CodeRelation(
                                        source=src.fully_qualified_name,
                                        target=e.fully_qualified_name,
                                        relation_type="EXTENDS",
                                    )
                                )

        return relations

    def _find_enclosing_entity(
        self, entities: list[CodeEntity], line: int
    ) -> CodeEntity | None:
        """查找包含指定行的实体（用于确定调用关系中的源实体）。"""
        for e in sorted(
            entities, key=lambda x: (x.line_start, x.line_end), reverse=True
        ):
            if e.kind == "method" and e.line_start <= line <= (
                e.line_end or e.line_start + 10
            ):
                return e
        for e in sorted(entities, key=lambda x: x.line_start):
            if e.kind == "class" and e.line_start <= line:
                return e
        return entities[0] if entities else None

    def _find_line_in_diff(self, diff: str, content: str) -> int:
        """在 diff 中查找指定内容所在的行号。"""
        for i, line in enumerate(diff.splitlines(), start=1):
            if content in line:
                return i
        return 0

    def _entity_to_dict(self, e: CodeEntity) -> dict:
        """将 CodeEntity 转换为字典格式。"""
        return {
            "name": e.name,
            "kind": e.kind,
            "file_path": e.file_path,
            "line_start": e.line_start,
            "line_end": e.line_end,
            "language": e.language,
            "modifiers": e.modifiers,
            "signature": e.signature,
            "fully_qualified_name": e.fully_qualified_name,
            "parent_class": e.parent_class,
            "package": e.package,
        }

    def _relation_to_dict(self, r: CodeRelation) -> dict:
        """将 CodeRelation 转换为字典格式。"""
        return {
            "source": r.source,
            "target": r.target,
            "relation_type": r.relation_type,
        }
