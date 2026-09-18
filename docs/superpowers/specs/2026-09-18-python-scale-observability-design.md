# Python 2→4 实例压测与低干扰观测设计

## 目标

为简历中的“分层架构解耦”提供可复核数据：

- Java BFF 异步受理在 20 req/s、30 分钟恒定到达率下的成功吞吐与受理 P95。
- Python 从开始处理任务到 `_process_message()` 完成的 P99，不包含 RESULT/DEAD_LETTER 回调发送、callback topic 排队、Java 回调消费和终态入库。
- 每个 Python 实例的进程 CPU 平均值、P95、最大值与离散程度。
- Kafka tasks/callbacks lag、Outbox、Java 内存/CPU/GC/连接池等稳定性证据。
- 2 实例与 4 实例在同口径下的对照结果，以及容量阶梯测试得到的最大可持续吞吐提升倍数。

## 指标边界

### Java 受理延迟

k6 计时范围为发起 `POST /api/review/async` 到收到 HTTP 202。该范围包含 Java AST 预处理、任务与 Outbox 落库，不包含 Kafka 排队和 Python 执行。

### Python 任务处理延迟

Python 消费者发送 PROCESSING 事件后开始计时，在 `_process_message()` 成功返回或最终确认失败时停止计时。计时包含 payload 拉取、请求解析、RAG/LLM/mock 流水线及进程内重试退避；不包含最终回调发送及后续 Java 入库。

使用低基数 Histogram：

```text
python_review_task_processing_seconds{instance,outcome}
```

标签只允许 `instance` 和 `outcome`，禁止 taskId、projectId、RunID 等高基数标签。

### CPU 口径

以 `process_cpu_seconds_total` 的速率计算，每个实例独立采集。报告同时保留“单核=100%”的核心等价值和按主机逻辑核数归一化后的整机占比，简历中必须明确所采用口径。

## 组件

### k6 场景

新增独立受理场景，使用 `constant-arrival-rate`：20 req/s、30 分钟。k6 只发送业务请求，不调用 Prometheus、Kafka CLI 或数据库。

输出：成功受理数、实际成功吞吐、P50/P95/P99、HTTP 失败率和 dropped iterations。原始 summary 保存为 JSON，最终报告从 JSON 读取，不依赖控制台文本解析。

### Python 埋点

在 Kafka 消费者 `_handle()` 中增加任务级计时。成功、最终失败分别记录 outcome；重试次数另设 Counter，避免把长尾误判为普通计算耗时。

### 独立采集器

采集器与 k6 分离，每 15 秒采集一次：

- Prometheus：Python CPU、Java heap/RSS/CPU/GC、Hikari、Outbox。
- Kafka lag：优先使用 Kafka Exporter/JMX；不可用时每 30 秒以低优先级执行一次 `kafka-consumer-groups.sh --describe`。
- MySQL：只在测试前与测试后按 RunID 对账，压测期间不轮询业务表。

测试结束后通过 Prometheus range query 离线计算平均值、P95、最大值、标准差、P99，不让查询负载进入业务压测窗口。

## 测试流程

### 监控开销校验

以相同 20 req/s 流量分别运行 5 分钟：关闭新增采集、开启新增采集。若受理 P95 变化超过 5% 或 Python CPU 变化超过 2 个百分点，则降低采样频率或移除高开销采集项。

### 稳态对照

每轮开始前清理测试 RunID 数据、Kafka lag 和 Redis 去重状态，并确认 Java、Kafka、MySQL 健康。

1. 启动 2 个 Python 实例，预热后执行 20 req/s × 30 分钟。
2. 等待 tasks/callbacks lag、Outbox 和业务状态全部排空。
3. 保存 2 实例原始数据。
4. 清理测试状态，启动 4 个 Python 实例并重新预热。
5. 使用完全相同请求、mock 延迟和 k6 参数重复测试。
6. 保存 4 实例原始数据并生成对照报告。

### 容量阶梯测试

固定 20 req/s 无法证明吞吐提升倍数，因此另设 20、30、40、50、60、80 req/s 阶梯。每档持续足够时间判断 lag 趋势，找到满足以下条件的最大持续吞吐：

- HTTP 失败率低于 1%。
- dropped iterations 为 0。
- tasks lag 不持续增长。
- 测试后 tasks/callbacks lag 与 Outbox 可恢复为 0。
- Python 处理 P99 不超过“2实例、20 req/s稳态基线 P99”的 120%；2/4 实例容量测试共用该阈值。

扩展倍数为 `4实例最大可持续吞吐 / 2实例最大可持续吞吐`。固定 20 req/s 的对照只用于比较 P99、单实例 CPU、lag 和资源稳定性。

## 结果文件

每次正式测试输出：

```text
2inst-result.json
4inst-result.json
2-vs-4-comparison.md
```

报告包含受理吞吐/P95、Python P99、各实例 CPU、tasks/callbacks lag、排空时间、Outbox、Java heap/RSS/GC/CPU/Hikari、成功/失败/重复/未完成任务数和容量提升倍数。

## 验收条件

- Python P99 的埋点结束点位于 RESULT/DEAD_LETTER 回调发送之前。
- 监控请求不由 k6 VU 发起。
- 监控开销校验通过。
- 2/4 实例测试使用相同数据、配置和持续时间。
- 所有报告数据可追溯到原始 k6 JSON、Prometheus 时间序列、Kafka lag 采样和数据库对账结果。
- 不用固定 20 req/s 的吞吐结果宣称 2→4 扩展倍数。
