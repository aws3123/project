# 20 req/s、30分钟 Python CPU 成本压测记录

## 1 测试概况

| 项目 | 内容 |
|---|---|
| 测试轮次 | Python CPU 成本采集轮 |
| RunID | `cpu-cost-30m-20rps-2inst-20260918T081437Z` |
| 项目ID | `perf-cpu-cost-30m-20rps-2inst-20260918T081437Z` |
| 测试场景 | `s1_decoupling`，异步受理恒定到达率 |
| Python实例 | 2个，端口8000/8001 |
| 到达率 | 20 req/s |
| 持续时间 | 30分钟 |
| LLM模式 | mock，`LLM_MOCK_DELAY_SECONDS=2` |
| 测试开始 | `2026-09-18T08:14:37Z`（北京时间 16:14:37） |
| k6流量结束 | 约 `2026-09-18T08:44:37Z` |
| 指标采集结束 | `2026-09-18T08:44:59Z` |

本轮目标是采集 Python 单任务 CPU 消耗及其占任务处理时长的比例，不进行 2→4 实例对照压测。

## 2 测试前基础设施

### 2.1 Kafka

| 参数 | 实际值 |
|---|---|
| Kafka Broker | 3个逻辑Broker，单机部署 |
| `ai.review.tasks` | 4分区，副本因子3，`min.insync.replicas=2` |
| `ai.review.callbacks` | 4分区，副本因子3，`min.insync.replicas=2` |
| `ai.feedback.events` | 4分区，副本因子3，`min.insync.replicas=2` |

### 2.2 应用实例

| 组件 | 实际值 |
|---|---|
| Java实例 | 1个，PID 677708 |
| Python实例 | 2个，PID 678269/678270，端口8000/8001 |
| Python进程启动方式 | uvicorn，单进程入口 |
| LLM mock延迟 | 2秒/次调用 |

## 3 测试脚本、命令和结果文件

### 3.1 测试脚本

- 本地场景脚本：`backend/k6/scenarios/s1_decoupling.js`
- 远程场景脚本：`/workspace/backend/k6/scenarios/s1_decoupling.js`
- 本地总控脚本：`backend/k6/tools/run_scale_benchmark.sh`
- 远程总控脚本：`/workspace/backend/k6/tools/run_scale_benchmark.sh`
- 指标采集器：`backend/k6/tools/collect_scale_metrics.py`
- 远程指标采集器：`/workspace/backend/k6/tools/collect_scale_metrics.py`

### 3.2 远程执行命令

```bash
cd /workspace/backend/k6
RATE=20 \
DURATION=30m \
RUN_PREFIX=cpu-cost-30m-20rps \
bash tools/run_scale_benchmark.sh --phase 2inst
```

### 3.3 远程结果目录

```text
/workspace/backend/k6/artifacts/cpu-cost-30m-20rps-2inst-20260918T081437Z/
```

主要文件：

- `k6.log`
- `k6-summary.json`
- `metrics-summary.json`
- `prometheus-raw.json`
- `python-metrics-before.json`
- `python-metrics-after.json`
- `kafka-lag.csv`
- `reconciliation.json`

## 4 k6受理结果

| 指标 | 结果 |
|---|---:|
| 受理请求数 | 36,001 |
| 目标到达率 | 20 req/s |
| 实际到达率 | 19.999857 req/s |
| HTTP失败率 | 0.000% |
| 受理检查 | 36,001/36,001 成功 |
| dropped iterations | 0 |
| 受理 P90 | 128.98 ms |
| 受理 P95 | 164.02 ms |
| 受理 P99 | 279.04 ms |
| 受理最大耗时 | 999.75 ms |

说明：本轮业务检查全部通过，36,001 个请求均返回受理成功及任务 ID。

## 5 Python处理与CPU成本

### 5.1 Python完成吞吐

采集窗口为 `1822` 秒，包含 k6流量结束后的 20 秒 Prometheus 稳定采集窗口。

| 指标 | 汇总值 |
|---|---:|
| Python完成任务数 | 25,450 |
| Python处理吞吐 | 13.968 req/s |
| Kafka消费消息数 | 26,567 |
| Kafka消费吞吐 | 14.581 req/s |

### 5.2 单任务CPU成本

该指标通过压测前后 Python Prometheus 指标差值计算：

```text
单任务CPU秒数 = process_cpu_seconds_total增量 / Python完成任务数
CPU时间占比 = process_cpu_seconds_total增量 / processing_seconds_total增量
```

| 实例 | 完成任务数 | 平均处理时长/任务 | CPU消耗/任务 | CPU时间占处理时长 |
|---|---:|---:|---:|---:|
| 8000 | 12,818 | 40.134 s | 5.030 s（5030 ms） | 12.533% |
| 8001 | 12,632 | 42.044 s | 5.057 s（5057 ms） | 12.028% |
| 汇总 | 25,450 | 41.082 s | 5.043 s（5043 ms） | 12.276% |

### 5.3 CPU利用率补充

| 实例 | 跨CPU核进程利用率 | 归一化到152逻辑核主机 |
|---|---:|---:|
| 8000 | 3447.71% | 22.682% |
| 8001 | 3451.15% | 22.705% |

说明：跨CPU核进程利用率超过100%是合法的多核进程统计口径；简历中应优先使用“单任务CPU消耗”和“CPU时间占处理时长”，不要直接使用未经说明的 3447% 数值。

## 6 Python处理耗时与Kafka积压

报告中的 `python_processing_p99_seconds` 为 Prometheus histogram quantile 序列的采样结果，不是每个任务逐条导出的原始 P99。该序列本轮结果为：

| 指标 | 值 |
|---|---:|
| p99 quantile序列平均值 | 96.944 s |
| p99 quantile序列 P95 | 115.585 s |
| p99 quantile序列最大值 | 115.709 s |

### Kafka lag

| Topic | 最大 lag | P95 lag | 最终 lag | 是否排空 |
|---|---:|---:|---:|---|
| `ai.review.tasks` | 6,111 | 6,000.4 | 6,023 | 否 |
| `ai.review.callbacks` | 31,519 | 30,169.6 | 31,519 | 否 |
| `ai.feedback.events` | 0 | 0 | 0 | 是 |

Outbox监测期间平均 pending 为 2,486.83，P95 为 4,941，最大值为 5,137。

## 7 测试结论

### 已验证

- Java BFF受理链路在 20 req/s、30 分钟流量下稳定运行；
- 累计成功受理 36,001 个请求，业务检查成功率 100%；
- 受理 P95 为 164.02 ms；
- Python 两个实例均有任务完成，单实例平均 CPU 消耗约 5.03～5.06 CPU秒/任务；
- CPU时间约占任务处理时长 12.276%，从该口径看，任务处理 wall-clock 时间主要不是 Python 本地 CPU 执行时间。

### 未验证或不支持的结论

- 本轮 Python 仅完成 25,450 个任务，低于受理的 36,001 个请求；
- `ai.review.tasks` 和 `ai.review.callbacks` 在窗口结束时仍有明显积压；
- 因此不能把 13.968 req/s 写成系统稳定吞吐，也不能宣称本轮异步链路完全排空；
- 本轮未采集 2→4 实例吞吐对照数据，不能得出扩容提升倍数；
- 本轮没有拆分 LLM、Kafka、MySQL 各自的等待时间，12.276% 只能说明 CPU 时间占 Python 处理 wall-clock 时间的比例，不能单独证明剩余时间分别由哪类 I/O 消耗。

## 8 简历使用建议

本轮可以安全支撑的表述是：

> 经 k6 以 20 req/s 恒定到达率持续 30 分钟验证，Java BFF 稳定受理 36,001 个异步请求，受理 P95 为 164.02 ms；Python 单任务平均 CPU 消耗约 5.04 s，占任务处理 wall-clock 时间约 12.28%。

不建议使用“系统稳定完成 36,000 个任务”或“吞吐瓶颈已转移至第三方 LLM”，因为本轮结束时 Kafka 仍有积压，且未采集 LLM 单独耗时与调用次数。
