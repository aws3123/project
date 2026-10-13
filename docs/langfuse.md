# Langfuse 接入

Python 审查链路使用 Langfuse Python SDK v4 的 observation API，和现有日志、
Prometheus 并行工作。现有模型客户端直接调用 AsyncOpenAI，因此在项目的
唯一 completion 入口记录 generation；图节点及工具使用显式 span，统一
依赖 OpenTelemetry 上下文关联父子关系，不重复挂载 LangChain CallbackHandler。

## 启用

在 Langfuse Cloud 或自建服务中创建项目 API keys，将以下值写入实际运行的
环境配置文件；密钥不写入源码。Compose 从 deploy/production/.env 读取：

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-REPLACE_WITH_PROJECT_KEY
LANGFUSE_SECRET_KEY=sk-lf-REPLACE_WITH_PROJECT_KEY
LANGFUSE_RELEASE=your-deployment-version
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_CAPTURE_CONTENT=false
```

自建服务替换 BASE_URL 即可。该接入不启动 Langfuse 服务端、不创建账户，
也不自动填写凭证。默认关闭；启用但缺少凭证或 SDK 初始化失败时记录日志，
审查链路继续执行。后台发送失败不会改变审查结果。生产密钥通过部署环境注入。

## 追踪结构

```text
review                         HTTP / SSE / Kafka 的一次执行尝试
└─ graph.execute               thread_id、图版本、new/resume/cached
   ├─ node.diff
   │  └─ tool.diff_analyzer
   ├─ node.rag
   │  └─ llm.structured
   │     └─ llm.completion     generation：模型、参数、真实 usage
   ├─ node.security            与 rules/performance 并行
   │  └─ react                可选 ReAct 子图
   │     ├─ react.decide → llm.structured → llm.completion
   │     ├─ react.tool → tool.<工具名>
   │     └─ react.answer 或 react.fallback
   ├─ node.scoring
   └─ node.report
```

根 observation 记录 task_id、Java traceId、project_id、mode、文件数、图版本、
是否启用 ReAct，以及最终状态、风险分数和人工复核标志。session_id 优先取
请求会话 ID，否则取 task_id。同一任务的重试各有执行 trace，按任务/会话关联；
已有 checkpoint 的成功结果直接复用，因此该次 trace 没有新的模型 generation。
直接调用业务风险 arun_state 时，以 graph.execute 为根。

节点降级标为 WARNING，异常记录类型并标为 ERROR。业务异常继续按原策略
传播；追踪层不吞掉业务错误。取消执行也会关闭 observation。

## Token、费用和内容

- 每次 _create_completion 记录一次 generation，包括文本、结构化、视觉及
  ReAct 请求。结构化输出的应用层重试分别记录；OpenAI SDK 内部网络重试
  属于同一次 completion observation。
- usage_details 使用响应的 prompt_tokens / completion_tokens / total_tokens，
  保留原 metered 计量逻辑。无 usage 或纯 mock 时不伪造 Token，metadata 的
  usage_source 标为 unavailable；Langfuse 展示的自动估算不代表实测用量。
- 费用取决于 Langfuse 中模型名称和价格配置，本接入不自行编造单价或金额。
- CAPTURE_CONTENT=false 时只传输入输出结构、长度/数量，以及明确选定的
  任务指标，不传提示词、代码、RAG 正文或模型回答。
- CAPTURE_CONTENT=true 时捕获经过截断及常见凭证字段遮盖的内容，默认单次
  输入/输出限制 8000 字符，可用 LANGFUSE_MAX_CONTENT_CHARS 调整。图像数据
  和 image_url 省略。字段遮盖属于尽力处理，不替代对待采集数据的审查。
- 异常正文不发送到 Langfuse，避免供应商错误响应携带输入内容或凭证。

SDK 使用批量后台发送；FastAPI 和 CLI 退出时调用 shutdown 排空待发送事件，
不在每个请求上同步 flush。LANGFUSE_TIMEOUT_SECONDS 默认 3 秒，用于 SDK
网络请求；LANGFUSE_SAMPLE_RATE 为 0–1，建议按实际流量选择。

本轮延续要求跳过测试和服务试跑；配置真实服务后才能确认界面中的追踪结果。

参考：[SDK](https://langfuse.com/docs/observability/sdk/overview)、
[Observation API](https://langfuse.com/docs/observability/sdk/instrumentation)、
[Token 与费用](https://langfuse.com/docs/observability/features/token-and-cost-tracking)。
