# 单机生产 Docker 部署设计

## 目标

在不改动业务源码的前提下，为 Sentinel 提供一套安全、可运维、可有限横向扩展的单服务器 Docker Compose 部署方案。宿主机既有 Nginx 负责 TLS 终止和公网入口。

## 范围与约束

- 只修改 Docker、Compose、容器 Nginx 和部署文档/环境变量模板；不修改 `backend/src`、`python/app`、`frontend/src`。
- 所有运行时密钥从未提交的 `deploy/production/.env` 注入；仓库仅提供 `.env.example`。
- 应用与基础设施不直接暴露公网。仅前端经 `127.0.0.1:<port>` 交给宿主机 Nginx 反代。
- MySQL、Redis、MinIO、Kafka、Elasticsearch、Chroma 数据均使用命名卷持久化。
- 每个服务使用固定镜像版本、健康检查、`unless-stopped` 重启策略、日志轮转和资源限制。

## 架构

`frontend` 是唯一发布宿主机端口的容器，绑定回环地址；宿主机 Nginx 将 HTTPS 请求代理到它。前端容器在私有网络中将 `/api/` 代理给 `java-backend`。Java 后端调用 `python-ai`，两个应用共享 MySQL、Redis、MinIO、Kafka 和 Elasticsearch。

Kafka 使用单节点 KRaft 模式，容器内地址统一为 `kafka:9092`。`kafka-init` 在 broker 就绪后创建任务、回调、反馈和死信 Topic；应用保持 `autoCreateTopics=false`。`minio-init` 创建报告和图片桶。

## 安全边界

- 数据库、缓存、对象存储、消息队列、向量/搜索库仅加入内部网络，不映射宿主机端口。
- Prometheus 与 Grafana如需启用，仅绑定 `127.0.0.1`，由宿主机 Nginx 按现有认证策略决定是否发布。
- 容器采用非 root 运行用户（适用的官方镜像除外），运行时镜像不包含构建工具。
- 生产配置不包含开发密码、LLM API Key、服务 API Key 或回调密钥。

## 扩展边界

Java 后端和前端是无状态或 Redis 共享状态的服务，可在单机资源允许的范围内通过 `docker compose up --scale` 扩容；Java 的业务 SSE 持久化后端配置为 Redis。Python AI 维持一个副本：当前源码只支持本地 `chromadb.PersistentClient`，多副本共享文件型 Chroma 数据目录存在并发写入风险。若未来要扩容 Python，必须先修改源码以支持独立的 Chroma 服务或其他远程向量库。

## 文件组织

- 根目录 `compose.yaml`：完整生产服务栈与依赖关系。
- `deploy/production/.env.example`：所有必需的非敏感变量和密钥占位符。
- `deploy/production/nginx-sentinel.conf.example`：宿主机 Nginx HTTPS 反代示例。
- 各服务 `Dockerfile` 与 `.dockerignore`：可复现、最小化的镜像构建。
- `frontend/deploy/nginx/default.conf.template`：容器内 API 反代、SSE 与静态资源策略。

## 验证标准

1. `docker compose --env-file deploy/production/.env.example config` 能解析全部服务且不包含未解析变量。
2. 三个应用镜像均可构建。
3. 未产生业务源码改动。
4. Compose 文件不再引用 `host-gateway`、`my-kafka` 或硬编码开发密钥。
