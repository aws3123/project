# 分层架构解耦压测

本目录提供可复核的 2→4 Python 实例压测工具。k6 只压 Java BFF 受理路径：

```text
k6 -> POST /api/review/async -> Java AST 预处理 -> Outbox -> HTTP 202
```

Python 处理 P99 从 Python 成功发送 `PROCESSING` 后起算，在 `_process_message()` 返回或最终失败前结束；不含 RESULT/DEAD_LETTER 回调、callback topic 排队和 Java 终态入库。指标为：

```text
python_review_task_processing_seconds{instance,outcome}
python_review_task_processing_retries_total{instance}
```

标签不含 taskId、projectId、RunID。

## 工具

- `scenarios/s1_decoupling.js`：20 req/s、30 分钟恒定到达率的受理压测；用 `--summary-export` 保存原始 k6 JSON。
- `tools/collect_scale_metrics.py`：独立采集器。Kafka 每 30 秒低优先级采样；压测后才查询 Prometheus，输出 CPU、Python P99、Kafka lag、Outbox 与 Java heap/RSS/CPU/GC/Hikari。
- `tools/run_scale_benchmark.sh`：2/4 实例、监控开销、容量阶梯的服务器编排器。凭据均通过环境变量提供。

## 首次执行

先把 Prometheus 的 `python-ai` job 改成 file-SD，并引用服务器上的 `/opt/monitoring/python-ai-targets.yml`；该文件由 runner 原子更新、再调用 `PROM_RELOAD_COMMAND` reload。先执行无副作用检查：

```bash
PYTHON_ROOT=/opt/review/python K6_ROOT=/workspace/backend/k6 \
PROMETHEUS_URL=http://localhost:9090 KAFKA_BOOTSTRAP=localhost:9092 \
KAFKA_CONSUMER_GROUP=review-python-consumer \
PROM_TARGETS_FILE=/opt/monitoring/python-ai-targets.yml \
PROM_RELOAD_COMMAND='curl -fsS -X POST http://localhost:9090/-/reload' \
bash /workspace/backend/k6/tools/run_scale_benchmark.sh --phase 2inst --dry-run
```

正式 2 实例、4 实例均使用相同 mock 延迟、数据与 20 req/s × 30 分钟配置：

```bash
bash tools/run_scale_benchmark.sh --phase 2inst
bash tools/run_scale_benchmark.sh --phase 4inst
```

`artifacts/<run-id>/` 保存 `k6-summary.json`、`kafka-lag.csv`、`prometheus-raw.json`、`metrics-summary.json`、日志和 RunID 对账结果。

## 质量门

先运行关闭/开启采集器的两轮 5 分钟、20 req/s 对照。只有受理 P95 变化不超过 5%，且 Python CPU 均值变化不超过 2 个百分点，才采纳正式压测数据。

固定 20 req/s 只能比较 P95、Python P99、每实例 CPU 与 lag 稳定性，不能证明扩展倍数。分别以 `--phase staircase --instances 2` 和 `--phase staircase --instances 4` 执行相同阶梯后，扩展倍数为：

```text
4实例最大可持续 req/s / 2实例最大可持续 req/s
```

最大可持续档位需同时满足 HTTP 失败率 <1%、dropped iterations 为 0、tasks lag 不持续增长、最终 tasks/callbacks lag 与 Outbox 均排空，且 Python P99 不超过 2 实例 20 req/s 基线 P99 的 120%。
