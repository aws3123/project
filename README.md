# Sentinel

> 面向代码变更的智能审查与发布风险分析平台。

Sentinel 将 React 前端、Spring Boot 编排层和 FastAPI AI 计算层组合为一条可同步执行、也可异步削峰的代码审查链路。它在确定性规则检查之外，结合 AST 实体提取、跨文件影响分析、历史事故检索和多智能体分析，生成可追踪的结构化审查结果。

## 架构全景

```
公网用户 / Webhook / PR 事件
              │ HTTPS
              ▼
┌──────────────────────────────────────────────────────────────────┐
│ 宿主机 Nginx（TLS 终止） → frontend（React 静态资源 + 容器 Nginx） │
│                              │ /api/ 反向代理                    │
└──────────────────────────────┼───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Java 编排层（Spring Boot）                                        │
│  API Key / TraceId · Tree-sitter AST 预处理 · Redis 幂等与缓存     │
│                                                                  │
│  POST /api/review/dispatch                                        │
│        │ 负载 + diff 特征 + 风险信号                              │
│        ├─────────────── SYNC ────────────────┐                   │
│        │                                      ▼                   │
│        │                         HTTP 调用 Python /ai/review/sync │
│        │                                                          │
│        └────────────── ASYNC ──▶ ReviewTask + Outbox（同事务）   │
│                                             │                     │
│  Kafka callbacks ◀──────────────────────────┘                     │
│        │ 持久化结果 / 状态机 / SSE 推送                           │
│        ▼                                                         │
│  前端：任务轮询或 GET /api/review/tasks/{taskId}/stream           │
└────────┬───────────────────────────────┬─────────────────────────┘
         │                               │
         │ ai.review.tasks                │ MySQL / Redis / MinIO
         ▼                               ▼
┌───────────────────────────────┐   ┌────────────────────────────┐
│ Kafka（KRaft）                 │   │ 状态与对象存储              │
│ tasks · callbacks · feedback   │   │ 任务、结果、Outbox、SSE 事件 │
└──────────────┬────────────────┘   └────────────────────────────┘
               │ 消费 tasks / 发送 callbacks
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Python AI 层（FastAPI + aiokafka Worker）                         │
│                                                                  │
│  diff → classifier → impact → RAG → [rules | security |         │
│  performance]（并行）→ scoring → report                         │
│                                                                  │
│  AST / NetworkX 影响分析 · LangGraph 超时与断路器 · 结构化报告    │
└──────────────┬───────────────────────────────┬───────────────────┘
               │                               │
               ▼                               ▼
┌───────────────────────────────┐   ┌────────────────────────────┐
│ ChromaDB + Elasticsearch       │   │ OpenAI 兼容 LLM 服务         │
│ 向量 + 关键词检索 → RRF 融合   │   │ 推理与报告生成               │
└───────────────────────────────┘   └────────────────────────────┘
```

## 主要能力

- **三种提交方式**：小变更可同步返回；大变更可异步入队；`dispatch` 根据 diff 大小、文件数、风险信号和系统负载自动选择路径。
- **多阶段分析**：`diff → classifier → impact → RAG → [rules | security | performance] → scoring → report`；同阶段专家并行执行，并可按变更特征裁剪。
- **变更影响评估**：Java 端 Tree-sitter 预处理，Python 端用 AST 和知识图谱计算调用/依赖影响半径。
- **历史经验召回**：ChromaDB 向量检索与 Elasticsearch 关键词检索通过 RRF 融合，为审查提供历史事故上下文。
- **可靠异步编排**：Kafka 任务与回调 Topic、Outbox 投递、失败重试、对账任务、Redis 幂等和 SSE 状态推送共同保障任务闭环。
- **人工与反馈闭环**：支持任务重试、人工 Handoff 和审查反馈的统计、导出与事故草稿处理。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | React 19、Vite 8、TypeScript、React Query、Zustand、Vitest、Playwright |
| 编排层 | Java 17、Spring Boot 3.2、Spring Cloud Stream、MyBatis-Plus、Redis、Kafka、Tree-sitter |
| AI 层 | Python 3.12、FastAPI、LangGraph、LangChain、NetworkX、ChromaDB、Elasticsearch |
| 基础设施 | MySQL 8.4、Redis 7、Kafka KRaft、MinIO、Prometheus、Grafana、Docker Compose |

## 生产部署

### 1. 准备配置

需要 Docker Engine 和 Docker Compose v2。完整栈包含搜索、消息队列和 AI 依赖，建议为 Docker 预留至少 10 GB 内存。

从模板创建未纳入版本控制的生产配置，并替换每个 `CHANGE_ME` 值：

```powershell
Copy-Item deploy/production/.env.example deploy/production/.env
```

至少配置 MySQL、Redis、MinIO、应用间认证、LLM 和 Grafana 的密码/令牌。`APP_HOST_PORT` 默认为 `8088`，Prometheus 与 Grafana 分别默认为 `9090` 和 `3001`，它们都只绑定到 `127.0.0.1`。

### 2. 校验并启动

```bash
docker compose --env-file deploy/production/.env config --quiet
docker compose --env-file deploy/production/.env up -d --build
docker compose ps
curl http://127.0.0.1:8088/health
```

浏览器入口为 `http://127.0.0.1:8088/`。Java 与 Python 的端口不映射到宿主机；应通过前端反代访问 API，而不是直接暴露内部服务。

### 3. 接入宿主机 Nginx

将 [`deploy/production/nginx-sentinel.conf.example`](deploy/production/nginx-sentinel.conf.example) 安装为宿主机的独立虚拟主机；替换域名、证书路径和 upstream 端口后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

模板已包含 HTTPS 跳转以及适用于 SSE 的 HTTP/1.1、禁缓冲和 300 秒读取超时设置。

### 数据备份与扩缩容边界

所有状态数据使用命名卷。升级或迁移前先停止写入，并使用卷备份；例如备份 MySQL：

```bash
mkdir -p backups
docker run --rm -v sentinel_mysql-data:/data -v "$(pwd)/backups:/backup" \
  alpine tar czf /backup/mysql-data.tgz -C /data .
```

同样应备份 `redis-data`、`minio-data`、`kafka-data`、`elasticsearch-data`、`chroma-data` 和监控卷。项目名默认为 `sentinel`；若通过 `--project-name` 覆盖，请先用 `docker volume ls` 确认实际卷名。

Java 编排层可以在资源允许时横向扩展；Python AI 服务当前必须保持单副本，因为 Chroma 使用本地文件持久化，多副本会产生并发写入风险。前端作为唯一宿主机入口也应保持单副本，除非另行配置负载均衡。

## 本地开发

本地开发需要 Java 17、Maven、Python 3.12 + `uv`、Node.js 22 + `pnpm`，以及可访问的 MySQL、Redis、Kafka、MinIO 和 Elasticsearch。可先运行完整 Compose 栈进行联调，或按各层配置文件连接已有基础设施。

```bash
# Java 编排层（默认开发配置使用 localhost:3307 的 MySQL）
cd backend && mvn spring-boot:run -Dmaven.test.skip=true

# Python AI 层（Windows 上不建议开启 --reload）
cd python && uv sync
cd python && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# React 前端（开发服务器将 /api 代理到 localhost:8080）
pnpm --dir frontend install
pnpm --dir frontend dev
```

Python 的本地变量示例见 [`python/.env.example`](python/.env.example)；Java 的开发与生产配置分别位于 `backend/src/main/resources/application-dev.yml` 和 `application-prod.yml`。切勿将真实密钥写入仓库。

## 常用接口

生产环境请经站点域名调用以下 `/api` 路径。若直接调试 Java 服务，必须带上与 `API_KEY` 一致的 `X-API-Key`。

```bash
# 同步审查：等待完整结果
curl -X POST http://localhost:8080/api/review/sync \
  -H 'Content-Type: application/json' -H 'X-API-Key: dev-key' \
  -d '{
    "projectId":"demo", "projectName":"Demo", "prUrl":"https://git.example.com/pr/1",
    "diffContent":"diff --git a/UserController.java b/UserController.java", "mode":"SYNC"
  }'

# 自动路由：由后端决定同步或异步
curl -X POST http://localhost:8080/api/review/dispatch \
  -H 'Content-Type: application/json' -H 'X-API-Key: dev-key' \
  -d '{
    "projectId":"demo", "projectName":"Demo", "prUrl":"https://git.example.com/pr/2",
    "diffContent":"diff --git a/OrderService.java b/OrderService.java", "question":"请检查安全与性能风险"
  }'

# 查询任务；任务 SSE 为 /api/review/tasks/{taskId}/stream
curl http://localhost:8080/api/review/tasks/{taskId} -H 'X-API-Key: dev-key'
```

主要 REST 资源如下：

| 路径 | 用途 |
| --- | --- |
| `POST /api/review/sync` | 同步审查；请求体 `mode` 必须为 `SYNC` |
| `POST /api/review/sync/stream` | 流式同步审查，返回 SSE |
| `POST /api/review/async` | 异步审查；请求体 `mode` 必须为 `ASYNC` |
| `POST /api/review/dispatch` | 根据变更特征自动路由 |
| `GET /api/review/tasks`、`GET /api/review/tasks/{taskId}` | 查询任务列表或详情 |
| `GET /api/review/tasks/{taskId}/stream` | 订阅异步任务状态 |
| `POST /api/review/tasks/{taskId}/retry` | 重试任务 |
| `POST /api/feedback/submit` | 提交审查反馈 |
| `POST /api/business-risk/source` | 上传 Java 源文件包，触发业务风险源包审查 |

## 测试与质量检查

```bash
# 前端：lint、单测与构建
pnpm --dir frontend test:ci

# Python：测试与静态检查
cd python && uv run pytest
cd python && uv run ruff check .

# Java：测试或打包
cd backend && mvn test
cd backend && mvn clean package -Dmaven.test.skip=true

# Docker Compose 配置渲染
docker compose --env-file deploy/production/.env.example config --quiet
```

## 项目结构

```text
.
├── frontend/                 React 单页应用和容器 Nginx 配置
├── backend/                  Spring Boot 编排、任务状态机、Outbox、SSE 与 API
├── python/                   FastAPI、LangGraph 分析管道、RAG 与 Kafka Worker
├── monitoring/               Prometheus 规则、Grafana 仪表盘与配置
├── deploy/production/        生产环境变量与宿主机 Nginx 模板
├── compose.yaml              完整生产 Docker Compose 拓扑
├── docs/superpowers/         已记录的设计与实施方案
└── backend/k6/               压测脚本与验证记录
```

## 相关资料

- [生产 Docker 部署设计](docs/superpowers/specs/2026-09-18-production-docker-design.md)
- [生产 Docker 部署实施计划](docs/superpowers/plans/2026-09-18-production-docker.md)
- [异步链路解耦说明](backend/k6/README_DECOUPLING.md)
- [异步链路韧性验证](backend/k6/README_RESILIENCE.md)

## 安全说明

- `deploy/production/.env` 已被忽略；只提交 `.env.example`。
- 生产环境仅映射前端、Prometheus 和 Grafana 到宿主机回环地址；数据与内部服务保持在私有网络。
- 外部 API 通过 `X-API-Key` 认证；内部回调使用独立 token；`X-Trace-Id` 贯穿前端、Java 与 Python 服务。
