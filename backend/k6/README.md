# k6 压测脚本（指标复现命令与门禁）

本目录收录 Sentinel 全部 k6 压测脚本，指标口径与仓库根 [README](../README.md)「核心指标自证」一致。

## 脚本清单

| 脚本 | 模式 | 验证目标 | 对应简历/README 指标 |
|------|------|---------|---------------------|
| [scenarios/async.js](scenarios/async.js) | `constant-vus` 封闭式等待 | 异步全链路端到端延迟与吞吐（Little's Law 自洽） | 吞吐 42→83→143 req/s · 延迟 24s→12s→7s |
| [scenarios/burst_3000.js](scenarios/burst_3000.js) | `per-vu-iterations` 一次尖峰 | 3000 VU 单次尖峰注入 3000 任务，受理层全量落库、零丢失 | 突发 3000 VU 尖峰任务零丢失 |
| [scenarios/steady_140.js](scenarios/steady_140.js) | `constant-arrival-rate` | 140 req/s × 30min 稳态受理吞吐、DLQ 零增量 | 稳态 140 req/s 零死信 |
| [scenarios/sse_300.js](scenarios/sse_300.js) | `per-vu-iterations`（依赖 `k6/x/sse`） | 300 个 SSE 长连接随机 10% 断线重连补偿 | SSE 300 连接断线零丢失 |
| [scenarios/sync.js](scenarios/sync.js) | `ramping-vus` | 同步链路响应能力（辅助，非简历核心） | — |
| [scenarios/dispatch.js](scenarios/dispatch.js) | `ramping-vus` | 自动路由分发决策（辅助，非简历核心） | — |
| [scenarios/mixed.js](scenarios/mixed.js) | `ramping-vus` | 混合用户行为（辅助，非简历核心） | — |
| [config.js](config.js) | — | 共享配置与请求体构造（sync / async / sync-stream） | — |

## 简历指标口径

- **吞吐 42→83→143 req/s / 延迟 24s→12s→7s（1000 VU / 5min）**
  阶段 1 = Python 单实例直连（AST 解析占 CPU ~65%，GIL 争用）→ 42 req/s；
  阶段 2 = AST 前置 Java BFF、Python 单实例 → 83 req/s；
  阶段 3 = Python 无状态双实例 → 143 req/s（整体 3.4×）。
  Little's Law 自洽：1000÷42≈24s / 1000÷83≈12s / 1000÷143≈7s。
- **突发 3000 VU 尖峰**：3000 VU 各提交 1 个异步任务，受理层全量落库（202 受理数 = 终态数）；Kafka 峰值积压约 3000 条，20~25s 内以 ~140 条/s 排空。
- **稳态 140 req/s × 30min**：约 25.2 万任务，DLQ 新增 = 0，Kafka Producer≈Consumer、Lag 低位稳定。
- **SSE 300 连接 + 10% 断线**：经 Last-Event-ID + Redis 事件快照增量追平，Lost=0 / Duplicate=0 / OutOfOrder=0。

## 运行命令

```bash
# 异步全链路（默认 1000 VU / 5min）
k6 run k6/scenarios/async.js

# 场景1：3000 VU 单次尖峰（注意：仅当 Kafka/DB 已与压测机隔离时使用）
k6 run --env VUS=3000 k6/scenarios/burst_3000.js

# 场景2：140 req/s × 30min 稳态
k6 run --env RATE=140 --env DURATION=30m k6/scenarios/steady_140.js

# 场景3：300 SSE 长连接 + 10% 断线重连（需 k6 ≥ v0.53 或 xk6 构建 xk6-sse 扩展）
k6 run --env VUS=300 --env DROP_EVERY=10 k6/scenarios/sse_300.js
```

## 前置条件

- k6 已安装；`sse_300.js` 需要 k6 ≥ v0.53（`k6/x/sse` 自动解析）或
  `xk6 build --with github.com/phymbert/xk6-sse@latest`。
- 后端已启动：Java BFF（8080）、Python（8000）、Kafka、MySQL、Redis（SSE 场景需
  开启 `review.stream.cache.enabled=true`）。
- 环境变量可覆盖：`TARGET_URL` / `API_KEY`。默认 `http://localhost:8080`，`X-API-Key: dev-key`。

## 全链路对账口径（配合监控）

Kafka / MySQL / Redis 侧指标（Lag、consumer rate、DLQ、落库计数）不在 k6 内采集，
由 Prometheus/Grafana + SQL 计数核对，与 k6 计数做对账：

```
k6 提交(202) = DB review_task 新增 = Outbox 新增
            = Kafka ai.review.tasks 消息数 = Python 处理数
            = Kafka ai.review.callbacks 消息数 = 终态任务数
DLQ 新增 = 0
```