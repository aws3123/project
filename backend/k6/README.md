# k6 压测 · 板块1：分层架构解耦（AST 前置 / 水平扩展）

## 叙事与指标的对应关系

| 简历叙事 | 指标 | 来源 | Grafana 面板 |
|---|---|---|---|
| 受理吞吐 42→83→143 req/s | 受理接口吞吐（req/s） | `http_server_requests_seconds_count{uri="/api/review/async"}` | 受理吞吐 / 5m 窗口 |
| 受理 P99 | `histogram_quantile` on `http_server_requests_seconds_bucket` | 同上 | 受理延迟分位 / 受理 P99 |
| AST 解析 P99（Java 侧） | `review_ast_parse_seconds` | 新增埋点 `AstMetricsService` | AST 预处理耗时分位 |
| Python CPU 95%→30%（GIL 证据） | `rate(process_cpu_seconds_total{job="python-ai"})` | prometheus_client 进程指标 | Python 进程 CPU |
| 水平扩展线性度 ≥90% | 每实例受理吞吐 | 受理吞吐 ÷ 实例数 | 每实例受理吞吐 |
| 原生解析覆盖质量 | `review_ast_native_fallback_total` 回退率 | 新增埋点 | 原生解析回退率 |

## 前置条件

1. 栈已启动：`docker compose up -d`（java-backend、python-ai、prometheus、grafana、kafka、mysql、redis）。
2. Prometheus 抓取 java-backend（`/actuator/prometheus`）与 python-ai（`/metrics`），配置见 `monitoring/prometheus/prometheus.yml`。
3. Grafana 看板自动装载：`monitoring/grafana/dashboards/s1-architecture-decoupling.json`（uid `s1-decouple`）。
4. k6 >= 0.49：https://grafana.com/docs/k6/latest/set-up/install-k6/

## 场景一：受理基线（恒定到达率，open workload）

受理接口是异步入口（落库即返回），**到达率才是自变量**，因此用 `constant-arrival-rate`
而不是并发 VU。分三档各跑一轮，得到「吞吐–P99」对应关系：

```bash
cd backend/k6
k6 run -e RATE=100 -e DURATION=5m scenarios/s1_admission.js
k6 run -e RATE=300 -e DURATION=5m scenarios/s1_admission.js
k6 run -e RATE=500 -e DURATION=5m scenarios/s1_admission.js
```

每轮结束输出一行汇总（目标速率 / 实际速率 / P50 / P95 / P99 / 失败率 / 受理成功数）。
质量门禁示例（不通过则退出码非 0，可用于流水线）：

```bash
k6 run -e RATE=300 -e FAIL_P99_MS=300 -e FAIL_HTTP_RATE=0.005 scenarios/s1_admission.js
```

可选参数：`DIFF_SIZE=small|medium|large`、`PRE_ALLOCATED_VUS`、`MAX_VUS`。

## 场景二：水平扩展阶梯（1 / 2 / 4 实例）

同一份阶梯（`BASE_RATE → 2× → 4×`，每档稳态 2m）分别在不同实例数下跑一轮：

```bash
# 1 实例
docker compose up -d --scale java-backend=1 java-backend
k6 run -e BASE_RATE=100 -e INSTANCES=1 scenarios/s1_scaling.js

# 2 实例
docker compose up -d --scale java-backend=2 java-backend
k6 run -e BASE_RATE=100 -e INSTANCES=2 scenarios/s1_scaling.js

# 4 实例
docker compose up -d --scale java-backend=4 java-backend
k6 run -e BASE_RATE=100 -e INSTANCES=4 scenarios/s1_scaling.js
```

结论读取方式：

- 每个实例数下「P99 与错误率不破门禁的最高稳态档」＝ 该规模的可持续受理吞吐；
- 每实例吞吐 ＝ 稳态档到达率 ÷ 实例数；跨实例数近似不变（线性度 ≥ 90%）即
  「具备水平扩展基础」的直接证据。

> 注意：Prometheus 的 `java-backend:8080` 静态目标对多副本是 DNS 轮询抓取，
> 「每实例吞吐」面板会轮流展示各副本；要严格的每实例曲线，可在
> `monitoring/prometheus/prometheus.yml` 里为每个副本增加独立端口的目标。
> Python 侧扩容同理使用 `docker compose -f docker-compose.python-scale.yml up -d --scale python-ai=N`。

每个请求都带 `stage=x1|x2|x4|ramp` 标签，配合下面的 remote write，
Grafana「k6 受理 P99（按扩展阶梯 stage）」面板可直接画分档曲线。

## 场景三：CPU 画像（瓶颈证据）

压测进行中（`RATE=300`）各采集 60s：

```bash
# Python：改造前应看到 AST/解析栈占 ~65%；改造后应看到 asyncio/网络栈为主
py-spy record --pid <python-ai-pid> -d 60 -o profile_python.svg --rate 50

# Java：前置后应看到 tree-sitter / TreeSitterPreprocessService 出现在热点里
# async-profiler:
./asprof -d 60 -f profile_java.html <java-backend-pid>
```

Python 进程 CPU 曲线（看板「Python 进程 CPU」）是 GIL 瓶颈的连续证据：
单进程上限 ~100%（1 核），改造前压测时打满、改造后回落。

## k6 结果写入 Prometheus（可选，推荐）

让 k6 指标与系统指标在同一时间轴上对比：

```bash
# Prometheus 需开启 remote write 接收：
#   command: ["--web.enable-remote-write-receiver", ...]（monitoring/prometheus/prometheus.yml 对应容器参数）
cd backend/k6
K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write \
K6_PROMETHEUS_RW_TREND_AS_HISTOGRAM=true \
k6 run --output=experimental-prometheus-rw -e RATE=300 scenarios/s1_admission.js
```

写入后可用看板底部「k6 压测数据」行（`k6_http_reqs_total` / `k6_http_req_duration_seconds_bucket`）。

## 新增指标清单（Java 侧）

| Prometheus 指标 | 含义 |
|---|---|
| `review_ast_parse_seconds{quantile,bucket...}` | 单次 AST 预处理耗时（同步受理路径内） |
| `review_ast_diff_bytes` | 进入预处理的 diff 载荷大小 |
| `review_ast_files_parsed_total` | tree-sitter 原生解析成功文件数 |
| `review_ast_native_fallback_total` | 原生解析失败回退正则路径文件数 |
| `review_ast_entities_extracted_total` | 原生路径提取的 AST 实体数 |

启用直方图的配置在 `backend/src/main/resources/application.yml` 的
`management.metrics.distribution`（`http.server.requests` 与 `review.ast.parse`）。
