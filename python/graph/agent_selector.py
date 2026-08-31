"""
Agent 选择器模块
===============

本模块是整个代码审查流水线的"调度中心"——它根据代码变更的特征（改了什么、改了多少、改在哪里），
智能决定需要运行哪些审查 Agent，避免"一刀切"地对所有变更都跑全套分析。

为什么需要智能选择？
-----------------
假设一次提交只改了 README 里的一行文字：
- 如果无脑运行所有 Agent（安全检查、性能分析、规则校验、RAG 检索），
  浪费 CPU 和时间不说，LLM 推理还要消耗 Token（= 烧钱）
- 这就像快递员只送一个信封，却开了一辆 10 吨卡车——大材小用，费油又费钱

反过来，如果一次提交删除了数据库表、改了密码逻辑，只跑个基础规则检查就放过——
那就是"用放大镜检查原子弹"，严重漏检。

选择策略（由轻到重）：
1. **平凡变更**（trivial）→ 跳过所有 Agent，直接通过
2. **小变更**（< 30 行）  → 只跑基础规则检查
3. **中等变更**          → 根据代码层次和 AST 语义，按需选择安全/性能 Agent
4. **大变更 / 高风险**   → 全量分析（规则 + 安全 + 性能）

关联概念：
- "Agent" 在这里指的是一个独立的分析模块（安全检查器、性能分析器、规则校验器），
  而不是 AI Agent，可以理解为"审查小组里的不同专家"
- "AST"（抽象语法树）= 编译器对代码的理解结果，就像把一篇作文拆成"主语-谓语-宾语"的结构化分析
- "RAG"（检索增强生成）= 从历史事故知识库中检索相关案例来辅助审查，
  已改为在本模块之前独立运行的前置节点
"""
from __future__ import annotations  # 延迟求值类型注解，提升启动速度

from graph.state import GraphState  # 流水线共享状态对象，所有节点通过它传递数据

# ══════════════════════════════════════════════════════════════════════
# 第一部分：阈值与关键词常量
# 这些是 Agent 选择的"决策参数"，集中定义方便调优，不需要改代码逻辑
# ══════════════════════════════════════════════════════════════════════

# ── 高风险关键词 ──────────────────────────────────────────────────
# 如果 diff（代码差异）中出现了以下任一关键词，说明变更涉及核心敏感操作，
# 必须触发全套审查（安全 + 性能），不能偷懒跳过
#
# 各关键词的风险说明：
#   DELETE / DROP / TRUNCATE → 数据破坏操作，删表删库跑路级别
#   password / secret / api_key / token → 敏感凭据相关，改错一行可能全站裸奔
#   @Transactional / lock / synchronized → 事务和锁相关，改错可能导致死锁或数据不一致
CORE_RISK_KEYWORDS = [
    "DELETE",
    "DROP",
    "TRUNCATE",
    "password",
    "secret",
    "api_key",
    "token",
    "@Transactional",
    "lock",
    "synchronized",
]

# ── diff 大小阈值 ──────────────────────────────────────────────────
# 变更行数超过此值 → 视为"大变更"，触发全量分析
# 为什么是 200 行？经验值：一次认知负荷合理的 code review 通常在 200-400 行，
# 超过这个量人工也审不过来，必须借助自动化工具全面扫描
LARGE_DIFF_THRESHOLD = 200  # 新增 + 删除行数总和超过此值 → 全量 Agent

# 变更行数低于此值 → 视为"微小变更"，只跑基础规则（如命名规范、代码风格），
# 安全/性能分析在这种规模下意义不大（比如改了一行注释，不需要检查 SQL 注入）
SMALL_DIFF_THRESHOLD = 30   # 新增 + 删除行数总和低于此值 → 仅规则检查

# ── 代码层次分类 ──────────────────────────────────────────────────
# 根据变更文件所属的代码层次（通过目录名/包名推断），决定审查方向：
# - 安全敏感层：controller / api / auth / security  → 优先触发安全审查
# - 性能敏感层：service / sql / repository / dao   → 优先触发性能审查
#
# 什么是"层次"？在分层架构中，代码按职责分为不同层，类似公司的部门分工：
#   Controller 层 = 前台接待（处理 HTTP 请求，对外暴露接口）
#   Service 层   = 业务经理（核心业务逻辑，承上启下）
#   Repository/DAO 层 = 档案室（数据库操作，CRUD）
SECURITY_LAYERS = {"controller", "api", "auth", "security"}
PERFORMANCE_LAYERS = {"service", "sql", "repository", "dao"}


# ══════════════════════════════════════════════════════════════════════
# 第二部分：辅助函数
# ══════════════════════════════════════════════════════════════════════

def _has_core_risk(state: GraphState) -> bool:
    """
    检查本次代码变更是否包含高风险关键词。

    遍历 diff 中每个文件的变更内容，看有没有命中 CORE_RISK_KEYWORDS 列表。
    只要有一个文件命中，就认为"存在核心风险"，返回 True。

    为什么用 .lower() 对比？
    - 代码中大小写不统一：有人写 "Delete"，有人写 "DELETE"，有人写 "delete"
    - 全部转小写后比较，确保不漏检（这就像机场安检不管你护照上名字大小写，能对上就行）

    Args:
        state: 流水线共享状态，包含 diff_analysis（代码差异分析结果）

    Returns:
        bool: True = 存在高风险，需要加重审查力度；False = 未见高风险
    """
    # 从状态中取出所有被修改文件的信息
    # state.get("diff_analysis", {}) 的写法有安全兜底：如果 diff_analysis 不存在也不会报错
    for f in state.get("diff_analysis", {}).get("files", []):
        # 取出该文件的 diff 文本（代码增删内容），统一转小写
        diff_text = f.get("diff", "").lower()
        # 检查是否有任何一个高风险关键词出现在 diff 中
        # any() 就像一个"快速扫描器"：遍历列表，找到第一个 True 就立即返回
        if any(kw.lower() in diff_text for kw in CORE_RISK_KEYWORDS):
            return True
    return False


# ══════════════════════════════════════════════════════════════════════
# 第三部分：核心选择函数
# ══════════════════════════════════════════════════════════════════════

def select_agents(state: GraphState) -> list:
    """
    根据 diff 特征，智能选择需要运行的审查 Agent。

    这是整个选择器的入口函数，决策逻辑分为三层：

    ┌──────────────────────────────────────────────────────────────┐
    │ 第一层：硬性判断                                              │
    │   · trivial 变更 → 直接返回空列表，不浪费任何资源             │
    │   · 高风险关键词命中 → 全量分析（安全 + 性能 + 规则）         │
    │   · diff > 200 行     → 全量分析                             │
    │   · 影响文件 > 5 个   → 全量分析                             │
    ├──────────────────────────────────────────────────────────────┤
    │ 第二层：规模判断                                              │
    │   · diff < 30 行 → 仅规则检查（没必要深度分析）               │
    ├──────────────────────────────────────────────────────────────┤
    │ 第三层：语义感知（中等变更）                                   │
    │   · 从 AST 实体中检测安全/性能注解和方法名                     │
    │   · 结合代码层次（controller → 安全，service → 性能）         │
    │   · 层级不明确时保守处理 → 也加上安全审查                      │
    └──────────────────────────────────────────────────────────────┘

    关于"保守处理"的设计哲学：
    - 漏检（该审没审）的代价远大于过检（不该审也审了）
    - 漏检可能导致线上事故，过检只是多花一点 CPU / Token
    - 所以当判断不确定时，宁可"宁可错杀一千，不可放过一个"

    Args:
        state: 流水线共享状态，包含了 diff_analysis、classification、
               impact_radius 等所有上游节点的分析结果

    Returns:
        list: Agent 列表，每个元素是 (名称, 执行函数) 的元组，
              如 [("rules", run_rule_checks), ("security", audit_security)]
              返回空列表表示"本轮无需审查"
    """
    # 延迟导入（Lazy Import）：只在函数被调用时才导入，而不是模块加载时
    # 好处：避免循环引用（A import B, B import A 的死锁），同时加快模块加载速度
    from graph.nodes import audit_security, analyze_performance, run_rule_checks

    # ── 第一层：平凡变更直接跳过 ──────────────────────────────────
    # trivial 标记由上游节点（如 diff 分析器）设定，例如：
    #   · 只改了注释 / 空白字符 / 格式化
    #   · 只改了配置文件里的一行
    if state.get("trivial"):
        return []

    # ── 从状态中提取分析所需的各项指标 ───────────────────────────
    # 代码所在层次（如 ["controller", "service"]）
    layers: list = state.get("classification", {}).get("layers", [])
    # diff 摘要信息（新增行数、删除行数等）
    diff_summary = state.get("diff_analysis", {}).get("summary", {})
    # 计算总变更行数 = 新增行数 + 删除行数
    diff_size = diff_summary.get("added_lines", 0) + diff_summary.get(
        "deleted_lines", 0
    )
    # 检查是否命中高风险关键词
    has_core_risk = _has_core_risk(state)

    # ── 第二层：AST 语义感知 ──────────────────────────────────────
    # 从 AST 解析结果中提取实体信息（类、方法、注解等），
    # 然后"闻味道"判断这个变更是否跟安全/性能相关
    #
    # 类比：就像医生看病，不仅看病人外表（文件路径），
    # 还要看化验单（AST 注解/方法名），综合判断该挂哪个科
    entities = state.get("diff_analysis", {}).get("entities", [])
    has_transactional = False      # 是否涉及事务注解 @Transactional
    has_security_entity = False    # 是否涉及安全相关方法/注解
    has_performance_entity = False # 是否涉及性能相关方法

    for entity in entities:
        annotations = entity.get("annotations", [])
        name = (entity.get("name", "") or "").lower()

        # 遍历该实体的所有注解（Java 的 @xxx 标记）
        for ann in annotations:
            ann_lower = ann.lower() if isinstance(ann, str) else ""
            # 事务注解 → 涉及数据库操作，需要性能审查
            if "transactional" in ann_lower:
                has_transactional = True
            # Spring Security 注解 → 涉及权限控制，需要安全审查
            # @PreAuthorize / @Secured / @RolesAllowed / @PermitAll
            # 这些都是 Spring Security 框架中用于方法级权限控制的注解
            if any(kw in ann_lower for kw in ("preauthorize", "secured", "rolesallowed", "permitall")):
                has_security_entity = True

        # 从方法名/类名中"闻味道"（命名约定推断意图）
        # 安全相关命名 → 很可能处理密码、Token、加密逻辑
        if any(kw in name for kw in ("auth", "login", "password", "token", "encrypt", "decrypt")):
            has_security_entity = True
        # 性能相关命名 → 很可能涉及批量操作、循环、数据库查询、缓存
        if any(kw in name for kw in ("batch", "loop", "stream", "query", "fetch", "cache")):
            has_performance_entity = True

    # ── 第三层：影响范围感知 ──────────────────────────────────────
    # 不仅看改了什么，还要看影响了多少文件
    # 影响文件越多 = 改动波及面越大 = 出问题的面也越大 → 需要更严格审查
    impact_radius = state.get("impact_radius", {})
    affected_count = len(impact_radius.get("affected_files", []))
    high_impact = affected_count > 5  # 超过 5 个文件受影响 → 高影响范围

    # ── 基础 Agent 列表：规则检查始终运行 ────────────────────────
    # 规则检查（run_rule_checks）是最轻量、最快的审查，
    # 只做静态检查（命名规范、代码风格、常见反模式），不涉及 LLM 推理，
    # 所以始终运行，零额外成本
    # 注意：RAG 检索已从此处移除，改为在本模块之前独立运行的串行前置节点
    agents: list = [("rules", run_rule_checks)]

    # ── 决策逻辑：根据风险等级追加 Agent ─────────────────────────
    if has_core_risk or diff_size > LARGE_DIFF_THRESHOLD or high_impact:
        # 【高风险路径】—— 三个条件满足任一即触发全量分析：
        #   1. 包含 DELETE/DROP/password 等敏感关键词
        #   2. 变更超过 200 行（人工难以全面审查）
        #   3. 波及超过 5 个文件（影响范围大，连锁反应风险高）
        agents.append(("security", audit_security))
        agents.append(("performance", analyze_performance))

    elif diff_size < SMALL_DIFF_THRESHOLD:
        # 【低风险路径】—— 变更不足 30 行，深度分析性价比极低
        # pass 表示不做任何追加，只保留基础规则检查
        pass

    else:
        # 【中等风险路径】—— 变更 30~200 行之间，根据语义精准选择 Agent

        # 安全审查条件：有安全注解/方法名 OR 文件在安全敏感层次
        if has_security_entity or any(layer in SECURITY_LAYERS for layer in layers):
            agents.append(("security", audit_security))

        # 性能审查条件：有事务注解 OR 性能相关方法名 OR 文件在性能敏感层次
        if has_transactional or has_performance_entity or any(layer in PERFORMANCE_LAYERS for layer in layers):
            agents.append(("performance", analyze_performance))

        # 保守兜底：如果层次被标记为 "other"（无法归类）且没有任何语义信号，
        # 仍追加安全审查——宁可多审，不可漏审
        # 这体现了"安全优先"的设计原则
        if layers == ["other"] and not (has_security_entity or has_performance_entity):
            agents.append(("security", audit_security))

    return agents
