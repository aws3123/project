# Python 层结构性重构：向 Java 经典分层对齐

## Context（背景与目标）

当前 `d:\AIPRO\python` 的目录骨架已具备 controller/service/repository 分层形态，但存在四处不符合 Java 规范的问题：

1. **`tools/` 万金油化**：静态检查器（领域检测器）与无状态纯工具、SPI 框架混在一个包
2. **`graph/nodes/` 领域逻辑与编排耦合**：审查专家（security/performance/scoring 等）的核心逻辑被绑死在 `(state, ctx) -> state` 节点签名上，无法脱离流水线复用与单测
3. **mapper 无收口**：ORM↔DTO 转换逻辑分散在各 `*_repository_sql.py` 内部
4. **`schemas/` 一包叠多型**：API 契约与领域模型混放，"字段给前端还是给 LLM 还是落库"分不清

目标结构（Java 映射）：

```
app/            # 装配层（routers=controller；dependencies=装配；main/exceptions/utils 不动）
services/       # service 层（registry.py → worker_registry.py 改名）
domain/         # 【新】领域层
  checkers/     #   静态检查器（从 tools 迁入，仍实现 tools.base.Tool 协议）
  reviewers/    #   审查专家纯函数（从 graph/nodes 抽出）
  shared/       #   diff_extractor 等跨审查器共享逻辑
  business_risk/#   业务风险 state/result 模型（本期仅机械迁移）
graph/          # 纯编排引擎（runner/builder/state/circuit_breaker/agent_selector + nodes/ 薄节点适配器）
repositories/   # 持久层 + mappers.py（ORM↔DTO 收口）
schemas/
  api/          #   request.py / result.py / backend_contract.py（对外契约）
  domain/       #   enums/task/log/llm_output/semantic_finding/business_risk*（领域模型）
tools/          # 仅留 SPI（base/registry）+ 无状态纯工具（ast_parser/diff_analyzer/code_knowledge_graph/incident_search）
config/ llm/ mq/ telemetry/   # 基础设施（不动）
```

**导入策略：干净断，不留兼容 shim**（已验证全项目 46 处直接 `from schemas.xxx import`，0 处聚合导入，无历史包袱）。

**已确认的用户决策**：
- Git：先提交现有改动到 main，再切 `refactor/layering` 分支
- 业务风险链路：本期仅机械迁移 state/result 模型，8 个业务节点的领域抽取留作后续迭代

## 关键现状事实（实施依据）

- 流水线装配唯一入口 [dependencies.py](file:///d:/AIPRO/python/app/dependencies.py)（L229-244 代码审查链路 / L271-283 业务风险链路），重构后装配行**不动**（节点函数名与位置不变）
- [agent_selector.py](file:///d:/AIPRO/python/graph/agent_selector.py) L159 延迟导入 `graph.nodes` 的 3 个 agent——**节点适配器必须保留在 graph/nodes/ 原文件名下**
- 节点调用检查器是字符串名派发（`ctx.registry.run("sql_risk_checker", ...)` 在 diff/classifier/impact/rules 节点）——检查器迁移**不改类内 `name` 属性**
- [graph/nodes/__init__.py](file:///d:/AIPRO/python/graph/nodes/__init__.py) 与 schemas/__init__.py 均有"双段重复块"（后者覆盖前者），需清理
- [conftest.py](file:///d:/AIPRO/python/tests/conftest.py) 有 `tools` 包 sys.modules 重绑定 hack（防 site-packages 遮蔽）——tools 拆分后**仍成立，不改**；但 `tools/__init__.py` 须保持轻量
- 基线已知失败：tests/integration/test_repo_wiring.py 引用不存在的 `mq.bus`（阶段 0 处理，避免污染回归信号）
- 两个字符串派发陷阱（IDE 重构改不到）：test_worker_registry.py 的 `monkeypatch("services.registry.asyncio.sleep")`；检查器注册名字符串
- mq/ 仅 review_consumer.py:14 一处 schemas 依赖；scripts/ 与 llm/ 零依赖；telemetry/hooks.py 有一处 schemas.log
- 运行环境：Windows + uv（`uv run pytest -q`，备选 `.venv\Scripts\python -m pytest -q`）

## 实施阶段（每阶段结束跑全量 `uv run pytest -q`，绿了才进下一阶段）

### 阶段 0：基线与工作区隔离
- 提交 main 上现有改动（backend Kafka 改造 + python/mq/ 未跟踪 + main.py/settings.py/pyproject 改动，一条 WIP 提交）
- 从干净 main 切 `refactor/layering` 分支
- 跑 `uv run pytest -q` 记录基线；修复或 xfail test_repo_wiring.py 的 `mq.bus` 引用

### 阶段 1：命名纠偏与重复块清理（零行为变更，~5 文件）
- `git mv services/registry.py services/worker_registry.py`（实为 WorkerRegistry 心跳客户端）；改 app/main.py 导入
- `git mv tests/services/test_registry.py tests/services/test_worker_registry.py` + 改导入 + **改 monkeypatch 字符串** `"services.registry.asyncio.sleep"` → `"services.worker_registry.asyncio.sleep"`
- 清理 [graph/nodes/__init__.py](file:///d:/AIPRO/python/graph/nodes/__init__.py) 双段重复（保留生效段，合并中文 docstring）
- `git mv tools/run_graph.py scripts/run_graph.py`（CLI 归位，已验证 0 引用）
- 验证：pytest 全量 + `import app.main` + `rg "services\.registry"` 清零

### 阶段 2：repositories/mappers.py 收口（~5 文件）
- 新建 `repositories/mappers.py`：**函数式**（模块级纯函数，与项目轻量风格一致，不引入 Mapper 类）
  - `task_to_model/task_to_schema`、`result_to_model/result_to_schema`、`log_to_schema`、`serialize_payload`、`apply_task_updates`
- 三个 `*_repository_sql.py` 改为薄仓储：session 管理不变，转换全部委托 mappers（迁移源自 [task_repository_sql.py](file:///d:/AIPRO/python/repositories/task_repository_sql.py) L92-102 `_to_schema` 等）
- 新建 tests/repositories/test_mappers.py（枚举往返、payload 序列化单测）

### 阶段 3：domain 包 + 检查器迁移（~9 文件）
- 新建 `domain/__init__.py`、`domain/checkers/__init__.py`
- `git mv tools/{sql_risk_checker,api_breaking_checker,config_change_checker,test_coverage_checker}.py domain/checkers/`（文件内 `from tools.base import ...` 不改，仍实现 Tool 协议——依赖方向 tools.registry → domain.checkers → tools.base，SPI 在 tools、实现在 domain，不成环）
- [tools/registry.py](file:///d:/AIPRO/python/tools/registry.py) 改 4 个导入；注册名不变
- `git mv tests/tools/test_rule_regression.py tests/domain/checkers/` + 改导入
- 验证：`build_default_registry()` 输出 8 个工具名不变；pytest 全量

### 阶段 4：diff_extractor 迁移（~5 文件）
- `git mv graph/nodes/diff_extractor.py domain/shared/diff_extractor.py`（已验证纯函数，仅 import logging/re）
- 改 graph/nodes/{security,performance,rag}.py 的导入路径
- 验证：`rg "graph\.nodes\.diff_extractor"` 清零

### 阶段 5：domain/reviewers 抽取（核心阶段，~15 文件）
按"一个审查器一个原子提交"推进：5a security → 5b performance → 5c scoring/report → 5d deduplicate/triviality/rag。

拆分范式（以 security 为范本，其余复刻）：

**新建 `domain/reviewers/security_review.py`**（纯函数+常量，禁止 import graph.state）：
- `DETERMINISTIC_PATTERNS`（原样迁移）
- `scan_deterministic(files: list[dict]) -> list[dict]`（原 `_deterministic_scan`，隐式 state 解包改为显式传参）
- `build_audit_messages(diff_snippet, method_names) -> list[dict]`
- `parse_llm_response(result) -> list[dict]`
- `merge_findings(det, llm) -> tuple[list, int]`

**改薄 [graph/nodes/security.py](file:///d:/AIPRO/python/graph/nodes/security.py)**（签名/函数名/文件名不变）：
- 读 state（files/impact_radius/code_graph）→ 调 domain → 写 state（security_findings/tool_logs）
- 降级分支（llm_client 为 None / 无 diff / LLM 失败）保留在节点侧

同范式拆分：performance(197 行)、scoring(232)、report(148)、deduplicate(89)、triviality_check(111)、rag(177，LLM 消息构建与 fallback 逻辑抽为 rag_analysis)。
**不拆**（纯编排节点，保留现状）：diff(28)、classifier(49)、impact(71)。
tests/graph/test_nodes.py 等现有测试**零改动**，作为回归锚点；可选为 domain 纯函数补最小单测。

验证：`rg -n "^from graph|^import graph" domain` 为 0；pytest 全量。

### 阶段 6：业务风险 state/result 机械迁移（~4 文件，按用户决策仅此深度）
- `git mv graph/business_risk_state.py domain/business_risk/state.py`
- `git mv graph/business_risk_result.py domain/business_risk/result.py`
- 改 [graph/business_risk_runner.py](file:///d:/AIPRO/python/graph/business_risk_runner.py)（runner 本体留 graph/，是编排包装）与相关导入
- 8 个业务风险节点**不动**（领域抽取留作后续迭代）
- 验证：`from graph.business_risk_runner import BusinessRiskRunner` 可导入；pytest 全量

### 阶段 7：schemas 拆分 api/domain（影响面最大、纯机械，~63 文件）
- `git mv schemas/{request,result,backend_contract}.py schemas/api/`
- `git mv schemas/{enums,task,log,llm_output,semantic_finding,business_risk,business_risk_review,business_risk_source,business_risk_source_result}.py schemas/domain/`
- schemas 内部相对导入调整（result→domain.enums 等；已验证 domain 不 import api，无反向依赖）
- 重写 schemas/__init__.py（删双段 re-export，已验证 0 处聚合使用）
- 批量替换 46 个导入方：`from schemas.request import` → `from schemas.api.request import` 等。涉及 app/(dependencies+routers×4)、graph/(runner/business_risk_*/nodes×4)、mq/review_consumer.py、repositories/×7、services/×8、telemetry/hooks.py、scripts/run_graph.py、tests/×14
- 验证：`rg "from schemas\.(request|result|backend_contract|enums|task|log|llm_output|semantic_finding|business_risk)"`（排除 schemas/ 自身）清零；TestClient 冒烟 `GET /health` 返回 200

### 阶段 8：收尾
- README 目录结构章节更新；Makefile consumer 目标修正（当前指向不存在的 mq/consumer.py）
- `uv run ruff check . --fix` + `uv run black .`
- 可选：pyproject 配置 ruff banned-api 固化分层规则（domain 禁 import graph/services/app）

## 风险与规避

| 风险 | 规避 |
|---|---|
| conftest 的 tools hack 失效 | 已分析仍成立，不改 conftest；保持 tools/__init__.py 轻量，阶段 8 用 ruff 禁止其 import domain |
| git rename 检测断链 | 只用 `git mv`；移动与内容修改分两个 commit；先隔离工作区（阶段 0） |
| 字符串派发改漏 | monkeypatch 字符串、检查器 name 属性绝不动；rg 清零断言兜底 |
| schemas 大范围替换出错 | 放最后阶段（前 6 阶段已稳定）；rg 清零断言 + TestClient 冒烟 |
| Windows 路径/大小写 | 全小写蛇形命名，无冲突；每阶段清理对应包 __pycache__ |

## 总工作量

约 110 文件次（新建 ~18 / 移动 ~23 / 修改 ~67）。阶段 1-4 纯机械；阶段 5 是唯一需逐文件判断"领域 vs 编排"的核心阶段；阶段 7 批量替换一次过靠断言兜底。

## 验证总纲

每阶段：`uv run pytest -q` 全量回归（基线失败清单外必须全绿）+ 该阶段专项断言（见各阶段）。最终：TestClient `/health` 冒烟 + ruff/black 通过 + `git log --follow` 抽查 rename 历史完整。
