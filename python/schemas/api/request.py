"""
审查请求数据模型
=================

作用：
    定义前端（或 Java 后端）发送给 Python 服务的"审查请求"数据结构。
    当前端调用"帮我审查这段代码"的接口时，发送过来的 JSON 数据就会被解析成这些模型。

什么是 Pydantic 的 BaseModel？
    BaseModel 是 Pydantic 库提供的基类，类似于 Java 中的 POJO/DTO。
    继承它之后，你就拥有了：
    1. 自动数据验证 —— 如果传入的数据类型不对（比如该传数字的地方传了字符串），会立刻报错
    2. 类型提示支持 —— IDE 能自动补全字段名
    3. JSON 序列化/反序列化 —— 可以方便地在 Python 对象和 JSON 之间转换
"""

# UUID 是"通用唯一识别码"，用来给每个任务生成一个不重复的 ID。
# uuid4 是基于随机数生成 UUID 的函数。
from uuid import UUID, uuid4
# Any 表示"任意类型"，Optional 表示"可以是 None"，List/Dict 是列表和字典的类型提示
from typing import Any, Optional, List, Dict

# BaseModel 是 Pydantic 的数据模型基类
# Field 用于给字段添加额外的约束和描述信息
from pydantic import BaseModel, Field

# 导入上面定义的枚举类型
from schemas.domain.enums import HandoffDecision, ReviewMode


# =============================================================================
# 文件变更模型 —— 描述单个文件的改动
# =============================================================================
class ReviewFileChange(BaseModel):
    """一次代码审查中，某个文件的变更内容。

    属性：
        path: 文件路径，比如 "src/main/java/com/acme/UserService.java"
        diff: 文件的 diff 内容（即 Git 风格的差异描述，记录了哪些行新增、哪些行删除）
    """
    # 文件在仓库中的路径
    path: str
    # diff 格式的代码变更内容
    diff: str


# =============================================================================
# 审查请求模型 —— 前端发来的完整审查请求
# =============================================================================
class ReviewRequest(BaseModel):
    """一次代码审查请求的完整数据。

    这是系统中最核心的数据模型之一，承载了发起一次审查所需的全部信息。
    """

    # 任务唯一标识。default_factory=uuid4 表示如果没有传入 taskId，
    # 就自动生成一个新的 UUID 作为 ID。
    taskId: UUID = Field(default_factory=uuid4)
    # 项目标识（哪个项目要审查）
    projectId: str
    # 仓库地址（代码仓库的 URL 或名称）
    repo: str
    # 分支名称（要审查哪个分支的代码）
    branch: str
    # diff 的 URL 地址（可选），如果 diff 内容太大，可能只传一个 URL
    diffUrl: Optional[str] = None
    # 变更的文件列表，每个元素是一个 ReviewFileChange 对象
    files: List[ReviewFileChange]
    # 审查模式：同步（SYNC）还是异步（ASYNC）
    mode: ReviewMode
    # 风险偏好配置，比如 {"security": 0.8, "performance": 0.5}
    # key 是风险维度名称，value 是权重（0~1）
    riskPreferences: Dict[str, float] = Field(default_factory=dict)
    # 额外的元数据，比如项目名称、来源等附加信息
    metadata: Dict[str, str] = Field(default_factory=dict)
    # 链路追踪 ID，用于在分布式系统中串联一次请求的完整调用链
    traceId: Optional[str] = None
    # 会话 ID，用于多轮对话场景（同一个对话上下文共享同一个 session）
    session_id: Optional[str] = None
    # 请求 ID，标识当前这一次请求
    request_id: Optional[str] = None
    # 对话轮次（第几轮对话），用于多轮对话场景
    dialog_turn: Optional[int] = None
    # 记忆上下文：之前对话中积累的关键信息摘要，避免每次都重复分析
    memory_context: Dict[str, Any] = Field(default_factory=dict)
    # 记忆版本号，用于判断记忆是否过期需要刷新
    memory_version: Optional[str] = None
    # 用户反馈信号：用户对之前审查结果的反馈（比如"这个误报了"）
    user_feedback_signals: Dict[str, Any] = Field(default_factory=dict)
    # 代码实体列表（类、方法等），由 Java 端 AST 解析得到
    entities: Optional[List[Dict[str, Any]]] = None
    # 实体之间的关系（比如"方法 A 调用了方法 B"）
    relations: Optional[List[Dict[str, Any]]] = None

    # Pydantic 模型配置
    model_config = {
        # populate_by_name=True 允许通过字段名或别名来填充数据
        "populate_by_name": True,
        # 不允许任意类型，确保数据安全性
        "arbitrary_types_allowed": False,
    }


# =============================================================================
# 人工审查请求模型 —— 人工介入时的决策数据
# =============================================================================
class HandoffRequest(BaseModel):
    """人工审查（Human-in-the-loop）的决策请求。

    当 AI 审查后不确定结果时，会交给人类审查。
    人类做出决策后，通过这个模型提交决策结果。
    """
    # 决策结果：通过 / 拒绝 / 需要修改
    decision: HandoffDecision
    # 操作人（做出决策的人的用户名或 ID）
    operator: str
    # 备注/评论（可选），比如"这里确实有 SQL 注入风险"
    comment: Optional[str] = None
"""Pydantic models describing incoming review requests."""

from uuid import UUID, uuid4
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field

from schemas.domain.enums import HandoffDecision, ReviewMode


class ReviewFileChange(BaseModel):
    path: str
    diff: str


class ReviewRequest(BaseModel):
    taskId: UUID = Field(default_factory=uuid4)
    projectId: str
    repo: str
    branch: str
    diffUrl: Optional[str] = None
    files: List[ReviewFileChange]
    mode: ReviewMode
    riskPreferences: Dict[str, float] = Field(default_factory=dict)
    metadata: Dict[str, str] = Field(default_factory=dict)
    traceId: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    dialog_turn: Optional[int] = None
    memory_context: Dict[str, Any] = Field(default_factory=dict)
    memory_version: Optional[str] = None
    user_feedback_signals: Dict[str, Any] = Field(default_factory=dict)
    entities: Optional[List[Dict[str, Any]]] = None
    relations: Optional[List[Dict[str, Any]]] = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": False,
    }


class HandoffRequest(BaseModel):
    decision: HandoffDecision
    operator: str
    comment: Optional[str] = None
