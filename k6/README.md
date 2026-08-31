# k6 压测脚本

Java BFF + Python 无状态多实例分层架构的性能验证压测脚本。

## 安装 k6

- **Windows (Chocolatey):** `choco install k6`
- **Windows (Scoop):** `scoop install k6`
- **macOS:** `brew install k6`
- **Linux:** 从 [k6 发布页](https://github.com/grafana/k6/releases) 下载 `.deb`/`.rpm`

## 快速使用

```bash
# 确保 Java BFF 已在 localhost:8080 运行

# 1. 同步审核场景（小 diff）
k6 run k6/scenarios/sync.js

# 2. 自动分发场景（小 diff）
k6 run k6/scenarios/dispatch.js

# 3. 混合场景（同步 + 分发 + 任务查询，按权重混合）
k6 run k6/scenarios/mixed.js
```

## 参数覆盖

```bash
# 指定目标地址（默认 http://localhost:8080）
k6 run --env TARGET_URL=http://192.168.1.100:8080 k6/scenarios/sync.js

# 指定 diff 大小（small: ~80B / medium: ~480B / large: ~1.8KB）
k6 run --env DIFF_SIZE=large k6/scenarios/dispatch.js

# 指定并发数与时长（混合场景）
k6 run --env VUS=150 --env DURATION=10m k6/scenarios/mixed.js

# API Key（默认为 dev-key）
k6 run --env API_KEY=prod-key k6/scenarios/sync.js
```

## 输出结果

```bash
# 输出到 CSV
k6 run --out csv=results/sync.csv k6/scenarios/sync.js

# 输出到 JSON
k6 run --out json=results/sync.json k6/scenarios/sync.js

# 输出到 InfluxDB（配合 Grafana 看板）
k6 run --out influxdb=http://localhost:8086/k6 k6/scenarios/mixed.js
```

## 实时可视化仪表盘（K6 v0.49.0+）

内置 Web Dashboard 可在测试运行时实时展示吞吐量、响应时间分布、错误率等关键指标：

```bash
# 方式一：环境变量启动（所有脚本通用）
K6_WEB_DASHBOARD=true k6 run k6/scenarios/sync.js

# 方式二：--out dashboard 输出
k6 run --out dashboard k6/scenarios/sync.js

# 组合其他输出（同时导出 CSV + 实时看板）
k6 run --out dashboard --out csv=results/sync.csv k6/scenarios/sync.js
```

访问 `http://localhost:5665` 查看实时图表。

### 实用参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `K6_WEB_DASHBOARD=true` | 启用内置仪表盘 | `K6_WEB_DASHBOARD=true k6 run script.js` |
| `--out dashboard` | 仪表盘输出方式 | `k6 run --out dashboard script.js` |
| `K6_WEB_DASHBOARD_EXPORT=report.html` | 测试结束后导出离线 HTML 报告 | `K6_WEB_DASHBOARD_EXPORT=report.html k6 run script.js` |
| `K6_WEB_DASHBOARD_PERIOD=5s` | 刷新间隔（默认 10s） | `K6_WEB_DASHBOARD_PERIOD=5s k6 run script.js` |
| `--out dashboard=open=false` | 启动但不自动打开浏览器 | `k6 run --out dashboard=open=false script.js` |

### 各场景启动示例

```bash
# 同步审核场景 + 仪表盘
k6 run --out dashboard k6/scenarios/sync.js

# 自动分发场景 + 仪表盘
k6 run --out dashboard k6/scenarios/dispatch.js

# 混合场景 + 仪表盘（带参数覆盖）
k6 run --out dashboard --env VUS=100 --env DURATION=5m k6/scenarios/mixed.js

# 图片审核 + 仪表盘
K6_WEB_DASHBOARD=true k6 run k6/scripts/image-review-load-test.js

# 反馈提交 + 仪表盘 + 导出离线报告
K6_WEB_DASHBOARD=true K6_WEB_DASHBOARD_EXPORT=report-feedback.html k6 run k6/scripts/feedback-submit.js
```

## 场景说明

| 脚本 | 端点 | 说明 | 关键阈值 |
|------|------|------|---------|
| `sync.js` | `POST /api/review/sync` | 同步审核全链路（Java → Python） | P99 < 2s, 可用性 > 99.5% |
| `dispatch.js` | `POST /api/review/dispatch` | 自动路由分发（特征提取 → 决策 → 执行） | P99 < 3s, 可用性 > 99.5% |
| `mixed.js` | sync / dispatch / task 混合 | 模拟真实用户的操作序列 | P99 < 5s, 可用性 > 99.5% |

## 质量门禁（与架构目标对齐）

| 指标 | 阈值 | 对应优化目标 |
|------|------|-------------|
| 请求失败率 | < 0.5% | 服务可用性 >= 99.5% |
| P99 延迟（同步） | <= 2s | P99 1.6s 目标 |
| P95 延迟（同步） | <= 1s | 整体低延迟保障 |
| 平均延迟 | <= 500ms | 良好用户体验 |

## 目录结构

```
k6/
├── config.js           # 共享配置（地址、认证、阈值、工具函数）
├── README.md           # 本文件
└── scenarios/
    ├── sync.js         # 同步审核场景
    ├── dispatch.js     # 自动路由分发场景
    └── mixed.js        # 混合工作负载场景
```
