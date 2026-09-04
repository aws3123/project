# Kafka 异步链路 MQ 化改造 —— 测试验收清单

> 改造内容：Java 审查任务通过 Outbox 下发 Kafka（Topic 1 `ai.review.tasks`）→ **Python 作为 Kafka 消费者**处理 → 处理结果经回调 Topic 2 `ai.review.callbacks` 回投 Java 驱动状态机 / SSE / 死信。
> 同步 HTTP 链路全部保留；Java 侧 `reviewTaskIn` / `reviewTaskDlqIn` 消费者已下线。

---

## 0. 前置条件（需启动的容器）

| 依赖 | 说明 | 校验命令 |
|---|---|---|
| Kafka | broker `my-kafka:9092`（需含 `ai.review.tasks` 与 `ai.review.callbacks` 两个 topic，可自动创建） | `docker compose ps` 或 kafka 客户端 `kafka-topics.sh --bootstrap-server localhost:9092 --list` |
| MySQL | Java 依赖的库（含新增列 `entities_json`/`relations_json`） | 见下方 S0 |
| Redis | Java SSE 注册 + Python 去重（`review:consumed:*`） | `redis-cli ping` |
| Python | 依赖 `aiokafka` 已通过 `uv sync` 安装 | `uv sync` |
| 环境变量 | Python 侧 `KAFKA_ENABLED=true`；Java 侧 `MQ_CALLBACK_TOPIC=ai.review.callbacks`（可选，有默认值） | — |

### S0. 数据库结构迁移
```sql
-- 若为存量库，需手动执行（新部署由 schema.sql 自动建列）：
ALTER TABLE review_task_payload ADD COLUMN entities_json LONGTEXT NULL;
ALTER TABLE review_task_payload ADD COLUMN relations_json LONGTEXT NULL;
```
验证：`SHOW COLUMNS FROM review_task_payload;` 应看到 `entities_json`、`relations_json` 两列。

---

## 1. 单元测试（无需容器，本地即可跑）

### 1.1 Java
```bash
cd backend
mvn -o test "-Dtest=ReviewCallbackConsumerTest,ReconciliationJobTest,OutboxPollerTest"
```
- `ReviewCallbackConsumerTest`：PROCESSING / RESULT（SUCCESS、HUMAN_REVIEW）/ DEAD_LETTER 三分支 + messageId 去重 + terminal 忽略。
- `ReconciliationJobTest` / `OutboxPollerTest`：构造器适配后的回归。

### 1.2 Python
```bash
cd python
.venv/Scripts/python.exe -m pytest -q          # 全量（部分用例依赖外网 tiktoken 下载，可跳过）
.venv/Scripts/python.exe -m py_compile mq/callback_producer.py mq/payload_client.py mq/review_consumer.py app/main.py
```

---

## 2. 集成验收（需先启动第 0 节全部容器）

### S1 正常链路（核心验收）
1. 订阅 SSE：
   ```bash
   curl -N http://localhost:8080/api/review/tasks/{taskId}/stream
   ```
2. 提交异步审查任务（`mode=ASYNC`）：
   ```bash
   curl -X POST http://localhost:8080/api/review/async \
     -H "Content-Type: application/json" \
     -d '{
       "taskId": "{taskId}",
       "projectId": "demo",
       "projectName": "demo-repo",
       "prUrl": "https://example.com/pr/1",
       "diffContent": "DELETE FROM users WHERE id = {input};",
       "mode": "ASYNC",
       "sessionId": "sess-1"
     }'
   ```
3. **预期**（SSE 按序收到三个事件）：
   - `status` → `QUEUED`（提交返回即推）
   - `status` → `PROCESSING`（Python 消费 Topic 1 后回投 PROCESSING 回调触发）
   - `result`（Python 处理完成回投 RESULT 回调触发，含 riskScore/riskSummary/details）
4. **预期**（数据库）：
   - `review_task` 状态：`PENDING → PROCESSING → SUCCESS`（或 `HUMAN_REVIEW`）
   - `review_result` 有对应结果行
   - `review_task_payload` 有 `diff_content`（entities/relations 有值时为 JSON）

### S2 Python 消费与 payload 回源
```bash
# Python 侧日志应出现消费记录与回调发送记录
docker logs <python-ai容器> --tail 50
# 直接验证 payload 拉取端点（Python 消费时走的就是它）
curl -H "X-API-Key: ${API_KEY}" http://localhost:8080/api/internal/review/payload/{taskId}
```
**预期**：返回 `{taskId, diffContent, entities, relations}`；Python 日志含 `Callback sent eventType=PROCESSING` 与 `Callback sent eventType=RESULT`。

### S3 消费失败重投（at-least-once + 幂等）
1. 提交一个异步任务。
2. 在 Python 处理中（PROCESSING 阶段）`kill -9` Python 进程。
3. 重启 Python 容器。
4. **预期**：
   - 未 commit 的消息被重新投递，任务继续完成（不重复发 RESULT 副作用——`review_result` 为覆盖写 upsert，天然幂等）。
   - Python 日志出现去重日志 `Duplicate task skipped`（`kafka_dedup_enabled=true` 时，重投后在 TTL 内再次看到同 taskId 会跳过）。

### S4 非法 diff → DEAD_LETTER → 任务 FAILED
1. 提交 `diffContent` 为空字符串的任务：
   ```bash
   curl -X POST http://localhost:8080/api/review/async -H "Content-Type: application/json" \
     -d '{"taskId":"{taskId}","diffContent":"","mode":"ASYNC","projectId":"p","projectName":"n","prUrl":"u"}'
   ```
2. **预期**：
   - Topic 2 出现 `DEAD_LETTER` 事件（errorCode=`EMPTY_DIFF`）。
   - `review_task` 状态 → `FAILED`；`review_result.error_code=EMPTY_DIFF`。
   - SSE 收到 `task_failed` 事件（若已订阅）。

### S5 回调幂等（重复 messageId）
1. 手动向 Topic 2 重放一条已消费过的回调消息：
   ```bash
   kafka-console-producer.sh --bootstrap-server localhost:9092 --topic ai.review.callbacks \
     --property parse.key=true --property key.separator=: \
     <<< '{taskId}:{"messageId":"{taskId}-result","eventType":"RESULT","taskId":"{taskId}",...}'
   ```
2. **预期**：Java 日志 `Duplicate callback ignored messageId=...`；任务状态不被二次改写（terminal 后到达直接忽略）。

### S6 回调丢失 → ReconciliationJob 兜底
1. 停掉 Python（不消费 Topic 1）。
2. 提交异步任务，等待 > 30 分钟（`STUCK_PENDING_THRESHOLD`）或临时调小阈值。
3. **预期**：`ReconciliationJob` 扫描到 stuck PENDING → 重建 Outbox 事件重新下发；任务最终收敛到终态。

### S7 Outbox 投递失败 → DEAD → 任务 FAILED
1. 停掉 Kafka，提交异步任务。
2. 等 Outbox 重试次数达到上限（`MAX_POLL_RETRY`）。
3. **预期**：`outbox_event` 状态 → `DEAD`；`review_task` 状态 → `FAILED`（`error_code=OUTBOX_DELIVERY_EXHAUSTED`）；SSE 收到 `task_failed`。

### S8 回调消费者自身 DLQ（Java 侧兜底）
1. 向 Topic 2 发送一条无法反序列化/消费抛异常的消息。
2. **预期**：Spring Cloud Stream 重试 3 次后进入 `ai.review.callbacks-dlq`；业务主链路不受影响。

---

## 3. 关键监控指标（验收时顺带确认有输出）

| 指标 | 位置 |
|---|---|
| Python 消费 lag（Topic 1） | Python telemetry / `kafka-consumer-groups.sh --describe --group python-review-worker` |
| Topic 2 消费 lag | `kafka-consumer-groups.sh --describe --group java-orchestrator-callback` |
| DEAD_LETTER 回调计数 | Python 日志 `Callback sent eventType=DEAD_LETTER` |
| 任务终态分布 / FAILED 率 | Java ConcurrentMetricsService / 指标端点 |

---

## 4. 回滚方案

| 层级 | 操作 | 说明 |
|---|---|---|
| 快速回滚 | Python `.env` 置 `KAFKA_ENABLED=false` 并重启 | 消费者/生产者完全不启动，回到纯 Java 编排（需先恢复 Java 消费者代码） |
| 完整回滚 | `git revert` 切换 commit（删除 `reviewTaskIn`/`reviewTaskDlqIn`、新增 `reviewCallbackIn` 的提交） | 恢复 Java 消费者与 HTTP 编排 |
| 数据安全 | 切换瞬间 Topic 1 可能短暂积压 | Kafka 缓冲不丢消息，Python 侧 `auto_offset_reset=earliest` 排干 |

---

## 5. 验收通过标准

- [ ] S1 正常链路 SSE 三事件齐全、任务落终态
- [ ] S3 杀 Python 后可重投完成、无重复副作用
- [ ] S4 非法 diff 进 DEAD_LETTER、任务 FAILED
- [ ] S5 重复回调被幂等忽略
- [ ] S7 Outbox DEAD 时任务 FAILED
- [ ] Java 单测、Python 语法/导入检查通过
