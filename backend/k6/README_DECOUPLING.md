# 分层架构解耦压测

本目录的 `s1_decoupling.js` 只测 Java BFF 的同步受理路径：

```text
k6 -> POST /api/review/async -> Java AST 预处理 -> Outbox -> 202 Accepted
```

脚本同时记录受理 P99，并由独立 sampler 从 Prometheus 采集任务完成 P99（`review_async_latency_seconds_bucket`）和 Python 进程 CPU 平均值，不会让每个 VU 轮询任务而干扰受理到达率。

## 运行

在 `backend/k6` 目录执行：

```bash
k6 run -e TARGET_URL=http://localhost:8080 \
  -e PROMETHEUS_URL=http://localhost:9090 \
  -e RATE=20 -e DURATION=5m -e DIFF_SIZE=small \
  scenarios/s1_decoupling.js
```

质量门禁可通过环境变量调整：

```bash
k6 run -e RATE=100 -e DURATION=5m \
  -e FAIL_P99_MS=500 -e FAIL_HTTP_RATE=0.01 \
  scenarios/s1_decoupling.js
```

脚本结束时输出目标速率、实际速率、P50/P95/P99、HTTP 失败率和 202 受理数。
同时输出 `task_completion_p99_prom_avg`（采样窗口内 Prometheus 任务完成 P99 的平均值）和 `python_cpu_avg`（Prometheus 查询结果的算术平均值）。

## 获取简历中的指标

分别在改造前/改造后或不同实例数下运行相同的 `RATE` 与 `DURATION`，保存每轮输出。压测期间从 Prometheus 查询：

```promql
# 受理吞吐
sum(rate(http_server_requests_seconds_count{uri="/api/review/async"}[1m]))

# 受理 P99
histogram_quantile(0.99, sum by (le) (
  rate(http_server_requests_seconds_bucket{uri="/api/review/async"}[1m])
))

# Python 进程 CPU 百分比；脚本内 sampler 使用同一查询
100 * sum(rate(process_cpu_seconds_total{job="python-ai"}[1m]))

# Java AST 预处理 P99
histogram_quantile(0.99, sum by (le) (
  rate(review_ast_parse_seconds_bucket[1m])
))
```

扩展线性度的计算方式：

```text
线性度 = (4 实例吞吐 / 1 实例吞吐) / 4 × 100%
```

每一轮必须记录实例数、目标到达率、实际受理吞吐、P99、失败率和 Python CPU；仅凭脚本输出不能证明 CPU 降幅或水平扩展线性度。
