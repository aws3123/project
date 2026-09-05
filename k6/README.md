# k6 压测脚本（重构版）

为 Java BFF + Python 无状态多实例分层架构设计，覆盖简历中 5 条性能/架构指标。
**数值口径说明：脚本不写死 42/202 等声称值，而是产出真实实测数据；你跑出的结果才是可信证据。**

## 安装

- Windows (Chocolatey): `choco install k6`
- Windows (Scoop): `scoop install k6`
- macOS: `brew install k6`
- Linux: 从 [k6 发布页](https://github.com/grafana/k6/releases) 下载

## 环境变量（config.js 统一读取）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BASE_URL` | `http://localhost:8080` | Java BFF 地址 |
| `PY_BASE_URL` | `http://localhost:8000` | Python 服务地址 |
| `API_KEY` | `dev-key` | 认证 Key |
| `MODE` / `VUS` / `DURATION` | `optimized` / 见 config | 指标1/2/3 通用：模式、并发数、时长 |
| `STABLE_RATE` / `STABLE_DURATION` | `200` / `30m` | 指标4 稳态到达速率(req/s)与时长 |
| `BURST_TARGET` | `500` | 指标4 突发并发峰值 |
| `COST_INPUT` / `COST_OUTPUT` | `3.2` / `9.5` | 指标3 成本计价（元/1M token），可覆盖 |

## 指标 → 脚本 → 复现命令

### 指标1：分层架构解耦（吞吐 42→202 req/s，4.8×）
同一脚本跑两次，比较 `baseline`(直连 Python 单实例，含 AST 解析) vs `optimized`(Java BFF AST 前置 + Python 多实例)。
脚本 `handleSummary` 直接打印实测吞吐、平均延迟与 Little's Law 推算（VU÷吞吐，应≈平均延迟，对得上=数据自洽）；提升倍数 = optimized ÷ baseline。

```bash
k6 run -e MODE=baseline  -e VUS=1000 -e DURATION=5m k6/scenarios/01-throughput.js --summary-trend-stats="avg,p(50),p(95)"
k6 run -e MODE=optimized -e VUS=1000 -e DURATION=5m k6/scenarios/01-throughput.js --summary-trend-stats="avg,p(50),p(95)"
```

### 指标2：多 Agent 并行 vs 串行（延迟降低约 40%）
触发 SSE 流式端点，测端到端延迟，并与 Σ各节点耗时(≈串行)对比，以 `parallel_savings_pct` 量化并行收益。

```bash
k6 run -e VUS=30 -e DURATION=5m k6/scenarios/02-agent-latency.js --summary-trend-stats="avg,p(95)"
```

### 指标3：上下文工程（Token ~16K / 成本 <¥0.1 / 合规率 99%+）
合规率在线实测（响应可解析 + 必填字段齐全）；Token/成本不虚构自响应体——响应体不含 usage 字段，
压测后用 SQL 聚合 `llm_usage`（BillingAspect 落库）产出 ~16K/次 与 <¥0.1 锚点：

```sql
SELECT task_id, SUM(prompt_tokens), SUM(completion_tokens)
FROM llm_usage WHERE task_id LIKE 'k6-ctx-%' GROUP BY task_id;
```

成本计价可经 `-e COST_INPUT/COST_OUTPUT` 覆盖。

```bash
k6 run -e VUS=50 -e DURATION=3m k6/scenarios/03-context-quality.js --summary-trend-stats="avg,p(95)"
```

### 指标4：流式输出与异步高可用（200 req/s 稳态 / 500 并发突发零丢失）
两个 executor 并行：`asyncStable`(constant-arrival-rate 200 req/s，默认 30m，对齐消费能力设计值 4×250信号量÷5s)
+ `concurrencyBurst`(ramping 至 500 并发，叠加在稳态之上)。
每个任务在提交它的迭代内轮询至终态（迭代内全量确认），结束时输出对账报告：
`async_submitted_total`(202受理) vs `async_terminal_total`(终态，含DEAD)，`async_reconcile_gap=0` 且 `async_dead_letter_total=0` 即零丢失；
突发段 `async_task_e2e_s` 的 max ≈ 积压消化（恢复）耗时。另含 SSE 流式可达与 Last-Event-ID 断线重连追平采样（观测项）。

```bash
# 冒烟（5 分钟）
k6 run -e STABLE_DURATION=5m k6/scenarios/04-streaming-availability.js --summary-trend-stats="avg,p(95)"
# 全量证据（200 req/s × 30m + 500 并发突发叠加）
k6 run k6/scenarios/04-streaming-availability.js --summary-trend-stats="avg,p(95)"
```

注意：200 req/s 稳态下在途 VU 约 1200+，突发叠加段峰值可达 ~5000，压测机需预留内存；机器不足时用 `-e STABLE_RATE=50` 降档。

### 指标5：数据闭环（反馈落库 + 统计检索）
提交反馈(201 落库)，并查询 `/stats` 验证数据可被检索，闭环可量化自证。

```bash
k6 run -e VUS=200 -e DURATION=3m k6/scenarios/05-feedback-loop.js
```

## 目录结构

```
k6/
├── config.js            # 统一配置（端点、阶段、阈值、认证、成本计价）
├── lib/helpers.js       # 共享工具（样例diff、trace header、SSE解析）
└── scenarios/
    ├── 01-throughput.js             # 指标1 分层解耦吞吐对比
    ├── 02-agent-latency.js          # 指标2 多Agent 并行vs串行延迟
    ├── 03-context-quality.js        # 指标3 上下文工程 token/成本/合规率
    ├── 04-streaming-availability.js # 指标4 流式输出+异步高可用(200 req/s 稳态+500 并发突发全量对账)
    └── 05-feedback-loop.js          # 指标5 数据闭环反馈
```

## 输出与可视化

```bash
# CSV/JSON 导出
k6 run --out csv=results/01.csv k6/scenarios/01-throughput.js
k6 run --out json=results/01.json k6/scenarios/01-throughput.js

# 实时仪表盘 (k6 v0.49+)
K6_WEB_DASHBOARD=true k6 run k6/scenarios/04-streaming-availability.js
k6 run --out dashboard k6/scenarios/01-throughput.js
```

## 已确认的端点契约

| 端点 | 方法 | 期望 |
|---|---|---|
| `/api/review/sync` | POST | 200 `ReviewSyncResponse` |
| `/api/review/sync/stream` | POST | SSE `run_started→step_*/→run_finished` |
| `/api/review/async` | POST | 202 `{taskId,status}` |
| `/api/review/dispatch` | POST | 200 `ReviewDispatchResponse{route,...}` |
| `/api/review/tasks/{id}` | GET | `{task:{status}, result:{...}}` |
| `/api/review/tasks/{id}/stream` | GET | SSE 任务事件流（Redis 快照+增量追平，支持 `Last-Event-ID` 断线重连） |
| `/api/feedback/submit` | POST | 201 `{id,status:"accepted"}` |
| Python `/ai/review/sync` | POST | 200 `ReviewResult` |

## 质量门禁（阈值，脚本内声明）

| 指标 | 阈值 |
|---|---|
| 请求失败率 | `<2%` |
| 输出格式合规率(指标3) | `>99%` |
| 异步提交受理率(指标4) | `>=99%` |
| 异步任务终态到达率(指标4) | `>99%` |
| 死信(指标4) | `<1` |
| 对账缺口/任务丢失(指标4) | `<1`（即 0，全量对账） |
| 反馈提交成功率(指标5) | `>=99.5%` |