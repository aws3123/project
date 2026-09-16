# 异步链路韧性验收

每轮必须设置唯一 `RUN_ID`。k6 以 `project_id=perf-$RUN_ID` 写入任务；数据库校验只统计这个范围，避免历史任务污染结论。真实 LLM 的排空、对账和故障恢复不由 k6 伪造，而由配套脚本验证。

## 1. 尖峰、全量落库与排空

```bash
export RUN_ID="spike-$(date +%Y%m%d%H%M%S)"
k6 run -e RUN_ID="$RUN_ID" -e PERF_RUN_ID="$RUN_ID" -e SCENARIO=spike -e SPIKE_TASKS=3000 scenarios/s2_resilience.js
uv run --project ../../python python tools/verify_async_run.py --run-id "$RUN_ID" --expected 3000 --wait-seconds 1800
```

最后一条命令输出 JSON。只有 `passed=true` 才能写“3000 全量落库、Outbox/终态差异 0”。`drainSeconds` 是最早任务落库到最后一个任务进入终态的实际排空总时长，真实速率为 `expected / drainSeconds`。

## 2. 30～60 分钟稳态浸泡

在一个终端启动观测，另一个终端进行持续入流：

```bash
export RUN_ID="soak-$(date +%Y%m%d%H%M%S)"
uv run --project ../../python python tools/observe_soak.py --duration-seconds 2700
k6 run -e RUN_ID="$RUN_ID" -e PERF_RUN_ID="$RUN_ID" -e SCENARIO=soak -e RATE=XXX -e DURATION=45m scenarios/s2_resilience.js
uv run --project ../../python python tools/verify_async_run.py --run-id "$RUN_ID" --expected XXX --wait-seconds 1800
```

`observe_soak.py` 给出 DLQ 增量、Python RSS 增长和异步端到端 P99 抖动比例。`expected` 应为实际 k6 成功受理数，而不是理论 `RATE × 时长`。

## 3. Kill 与 rebalance

先运行浸泡流量，然后在 Docker 主机执行。该脚本只有在 Kafka consumer group 再次出现已分配消费者后才返回，`rebalance_seconds` 是 kill 发起到 consumer group 恢复的实测时间；之后必须再次运行数据库对账。

```bash
RESULT_FILE=consumer-chaos.env tools/chaos_kill.sh consumer
RESULT_FILE=broker-chaos.env tools/chaos_kill.sh broker
```

仅在测试环境执行。当前基础设施是单 Broker；broker kill 验证的是“服务恢复后的消费恢复”，不是多副本 Kafka 的容灾承诺。

## 4. 重复投递与报告幂等

先用尖峰场景提交 1 个任务并等待其终态，再重复生产相同 `taskId` 的 Kafka 消息：

```bash
export RUN_ID="duplicate-$(date +%Y%m%d%H%M%S)"
k6 run -e RUN_ID="$RUN_ID" -e PERF_RUN_ID="$RUN_ID" -e SCENARIO=spike -e SPIKE_TASKS=1 scenarios/s2_resilience.js
uv run --project ../../python python tools/verify_async_run.py --run-id "$RUN_ID" --expected 1 --wait-seconds 600
uv run --project ../../python python tools/duplicate_delivery.py --run-id "$RUN_ID" --count 3
sleep 15
uv run --project ../../python python tools/verify_async_run.py --run-id "$RUN_ID" --expected 1
```

第二次对账的 `duplicateResultTasks=0` 与 Grafana 的 `5m 去重消息数=3` 共同证明消息真实到达且报告没有重复落库。

## 5. 300 个 SSE 与 10% 断线补齐

先用 k6 生成 300 个任务，再由 Node 20+ 客户端创建真实可中止的 SSE 长连接；原生 k6 HTTP 客户端会缓冲 SSE 响应，无法可靠地在事件中途断开连接。

```bash
export RUN_ID="sse-$(date +%Y%m%d%H%M%S)"
k6 run -e RUN_ID="$RUN_ID" -e PERF_RUN_ID="$RUN_ID" -e SCENARIO=sse -e SSE_TASKS=300 scenarios/s2_resilience.js
RUN_ID="$RUN_ID" SSE_TASKS=300 SSE_DISCONNECT_PERCENT=10 node tools/sse_reconnect.mjs
```

Node 脚本要求每个任务收到 `status` 与终态事件；固定抽取 10% 连接在收到首个带 ID 事件后主动中断，以 `Last-Event-ID` 重连。只有 `completionRatio=1`、`disconnected=30` 才能写“补齐率 100%”，`avgReconnectMs` 是简历中的平均重连耗时。
