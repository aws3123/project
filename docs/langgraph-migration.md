# LangGraph 运行与迁移说明

主审查入口（HTTP、SSE、Kafka）共用缓存的 AIService 和编译图。
GraphBuilder 仍提供原有节点/并行组装配方式，其产物由 StateGraph 调度。
graph/runner.py 只保留兼容导入，不再包含线程池或手工阶段执行循环。

## 图结构与节点契约

diff → classifier → impact → 可选 jev_route → rag → reviewer selector
→ [rules | security | performance] → barrier → scoring → report。

选择器保留确定性路由、Jev 仅追加审查方向和空选择回退全量的行为。
未选中的专家分支返回 SKIPPED，不调用模型或工具；屏障等待全部分支结束。
这些分支仍会输出对应的 SSE step_started / step_finished 事件。
SSE 保持 SUCCEEDED/FAILED 的既有状态词汇：SKIPPED 映射为 SUCCEEDED，
熔断和取消映射为 FAILED；图状态和节点日志保留完整的内部状态。

节点通过 node_input 获取隔离的工作副本，通过 node_output 发布显式拥有的
字段；tool_logs 只发布新记录，由 Annotated reducer 追加。并行节点禁止发布
完整输入状态。node_status 按节点名合并。新增状态字段必须加入 GraphState。
LLM、工具注册表、日志服务及 SSE 接收器放在运行上下文中，不存入 checkpoint。

ReAct 决策循环也使用 StateGraph，保留工具白名单、决策次数上限、结构化终答
校验与单次调用降级。在主审查节点内调用时，子图使用父图的 checkpoint 上下文。

## 本地与生产配置

本地默认 GRAPH_CHECKPOINT_BACKEND=memory；重启会丢失 checkpoint。
生产启动拒绝 memory，要求 GRAPH_CHECKPOINT_BACKEND=redis 和独立的
GRAPH_CHECKPOINT_REDIS_URL。连接和索引在 FastAPI lifespan 初始化，停止
Kafka 消费者后再关闭 checkpointer。CLI run_graph.py 同样管理这些资源。

Compose 新增 graph-checkpoints（Redis 8）和 graph-checkpoint-data 持久卷，
不暴露主机端口。原业务 Redis 7 继续承担缓存和 Kafka 租约。
Redis checkpointer 依赖 RedisJSON/RediSearch，不能直接连接普通 Redis 7。
独立实例开启 AOF，并采用 appendfsync always；实际吞吐需部署后测量。

GRAPH_CHECKPOINT_TTL_SECONDS 默认 86400；存储后端以分钟为单位向上取整，
读取会刷新保留时间。该期限应覆盖 Kafka 重投及人工重试窗口。
GRAPH_VERSION 默认 review-v1，修改节点业务语义时应升级版本。

## 执行身份与恢复

thread_id 由图版本、拓扑摘要及 task_id/执行标识构成。执行标识优先使用
state.run_id、request.request_id、metadata.execution_id，否则使用 task_id。
同一次失败重试必须复用执行标识；主动重新审查应分配新任务或新执行标识。
相同执行标识对应不同输入会被拒绝；traceId/trace_id 和传输 mode 的变化不影响恢复。

恢复先读取图快照，有未完成节点时使用 ainvoke(None) 继续；已有完整图状态
则直接转换为 ReviewResult，供 Kafka 重发结果回调，不重新消耗审查 Token。
成功 checkpoint 保留至 TTL，不在回调前删除。回调投递与 Kafka offset 提交
仍由消费层管理；图状态持久化不提供业务副作用的 exactly-once 保证。
图执行使用进程内锁及 Redis 可续租租约，避免重复投递同时修改同一 thread。
租约丢失会中止执行，交由调用方重试。副作用仍需调用方幂等处理。

## 失败策略

- GRAPH_PARALLEL_FAILURE_MODE=degrade（默认）：专家超时/异常记为 FAILED，
  或熔断记为 CIRCUIT_OPEN；继续生成报告，强制人工复核。降级分支视为完成，
  后续重试不会自动补跑该专家；需发起新执行。
- GRAPH_PARALLEL_FAILURE_MODE=raise：专家异常使图失败；重试从失败位置
  继续，已持久化成功分支可复用。熔断期间保持失败状态，等待后续重试。
- 串行节点异常终止图；节点内部已有的确定性/LLM 降级策略继续生效。
- 顺序和并行节点的日志、SSE step 事件由包装器产生，最终结果转换异常也会
  输出 run_error。SSE 客户端断开后继续执行的现有行为保持。

同步 run/run_state 为无事件循环的兼容入口。共享生产异步连接的调用方应使用
arun/arun_state，避免跨事件循环复用 Redis 连接。
业务风险包装器提供 arun，热点扫描和业务风险 RAG 节点也使用异步客户端接口；
此次不额外启用原本未挂载的业务风险路由或补充其余业务依赖。

## 从旧版本上线

1. 先暂停新任务接入并排空旧 worker，在旧版本上完成仍需恢复的任务。
2. 更新依赖锁文件对应的运行环境，创建 graph-checkpoints 服务及持久卷。
3. 使用新 Compose 配置启动 Python AI 服务；初始化失败会阻止服务启动。
4. 恢复任务接入。同一部署中不要让新旧引擎争抢同一个未完成任务。

旧 ckpt:* JSON 与 LangGraph 的快照格式不兼容，不自动转换；旧数据按原 TTL
过期。强行中断旧任务后再交给新版本，会从头执行。需要回滚时同样先排空
新 worker；旧引擎不能恢复新图的 checkpoint。拓扑摘要隔离不同节点布局，
但不能替代部署时排空存量执行。

本次按要求跳过测试与服务试跑。既有测试中依赖旧 checkpoint_service 参数、
完整状态返回值或手工阶段 checkpoint 的断言，需要后续迁移到新契约再执行。
