"""领域层（Java domain 对齐）—— 与基础设施解耦的业务与审查核心逻辑。

子包：
- checkers:    静态检查器（SQL/API/配置/测试覆盖），仍实现 tools.base.Tool SPI
- reviewers:   审查专家纯函数（阶段 5 抽取）
- shared:      跨审查器共享逻辑（diff_extractor 等，阶段 4 迁移）
- business_risk: 业务风险 state/result 模型（阶段 6 迁移）

依赖方向：domain 不依赖 app/services/graph（编排层），只依赖 tools（SPI）与 schemas。
"""