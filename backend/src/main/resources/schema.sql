CREATE TABLE IF NOT EXISTS review_task (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL UNIQUE,
    project_id VARCHAR(128),
    project_name VARCHAR(255),
    submitter VARCHAR(255),
    status VARCHAR(32),
    mode VARCHAR(32),
    priority VARCHAR(64),
    trace_id VARCHAR(128),
    handoff_decision VARCHAR(32),
    handoff_operator VARCHAR(255),
    handoff_comment TEXT,
    handoff_handled_at TIMESTAMP NULL,
    retry_count INT NOT NULL DEFAULT 0 COMMENT 'MQ 重试次数',
    version INT NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
    pr_url VARCHAR(512) COMMENT 'PR 链接',
    question VARCHAR(2000) COMMENT 'dispatch 模式的审查问题',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS review_result (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL,
    risk_score DECIMAL(5,2) COMMENT '风险评分 0.00~100.00',
    risk_summary TEXT COMMENT 'LLM 生成的审查摘要',
    need_human_review BOOLEAN NOT NULL DEFAULT FALSE,
    details LONGTEXT,
    logs LONGTEXT,
    error_code VARCHAR(128),
    error_message LONGTEXT,
    created_at TIMESTAMP NOT NULL
);

-- 单列唯一索引: 保证 task_id 1:1 关系
CREATE UNIQUE INDEX idx_review_result_task_id ON review_result(task_id);

-- 复合索引: 按状态+模式查询 (EXPLAIN: type=ref, key=idx_review_task_status_mode, rows<100)
CREATE INDEX idx_review_task_status_mode ON review_task(status, mode);

-- 复合索引: 按项目+状态查询 (覆盖索引，含 created_at 避免回表)
-- EXPLAIN: type=ref, key=idx_review_task_project_status, Extra=Using index condition
CREATE INDEX idx_review_task_project_status ON review_task(project_id, status, created_at);

-- 按创建时间倒序分页 (游标分页主索引)
CREATE INDEX idx_review_task_created_at ON review_task(created_at DESC);

-- ==========================================
-- Diff 内容载荷表: 从主表拆分 LONGTEXT 避免查询膨胀
-- ==========================================
CREATE TABLE IF NOT EXISTS review_task_payload (
    task_id VARCHAR(128) PRIMARY KEY COMMENT '关联 review_task.task_id',
    diff_content LONGTEXT NOT NULL COMMENT '原始 diff 内容',
    entities_json LONGTEXT NULL COMMENT 'Java TreeSitter AST 实体序列化 JSON',
    relations_json LONGTEXT NULL COMMENT 'Java TreeSitter AST 关系序列化 JSON',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 存量库迁移: 新部署走上面 CREATE TABLE, 存量库走下面 ALTER (continue-on-error 兜底重复列)
ALTER TABLE review_task_payload ADD COLUMN entities_json LONGTEXT NULL COMMENT 'Java TreeSitter AST 实体序列化 JSON' AFTER diff_content;
ALTER TABLE review_task_payload ADD COLUMN relations_json LONGTEXT NULL COMMENT 'Java TreeSitter AST 关系序列化 JSON' AFTER entities_json;

-- result 联合 task_id + created_at 避免回表
CREATE INDEX idx_review_result_task_created ON review_result(task_id, created_at);

-- ==========================================
-- Outbox 事件表: 保证 DB ↔ MQ 原子性
-- ==========================================
CREATE TABLE IF NOT EXISTS outbox_event (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL UNIQUE COMMENT '事件唯一ID',
    aggregate_type VARCHAR(64) NOT NULL COMMENT '聚合类型: review_task',
    aggregate_id VARCHAR(128) NOT NULL COMMENT '聚合ID: taskId',
    event_type VARCHAR(64) NOT NULL COMMENT '事件类型',
    payload JSON NOT NULL COMMENT '序列化的消息体',
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING | SENT | FAILED',
    retry_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    sent_at TIMESTAMP NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_outbox_status (status, created_at)
);

-- ==========================================
-- 幂等消费记录表: 防止重复处理 MQ 消息
-- ==========================================
CREATE TABLE IF NOT EXISTS consumed_message (
    message_id VARCHAR(128) PRIMARY KEY COMMENT 'MQ 消息 ID',
    task_id VARCHAR(128) NOT NULL,
    consumed_at TIMESTAMP NOT NULL
);

-- ==========================================
-- 审计日志表: 记录任务状态变更的完整追溯链
-- ==========================================
CREATE TABLE IF NOT EXISTS task_audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL,
    from_status VARCHAR(32),
    to_status VARCHAR(32),
    operator VARCHAR(64) COMMENT 'SYSTEM|MQ_CONSUMER|OUTBOX_POLLER|RECONCILIATION|DLQ_CONSUMER|HUMAN',
    detail TEXT,
    created_at TIMESTAMP NOT NULL,
    INDEX idx_audit_task_id (task_id),
    INDEX idx_audit_created_at (created_at)
);

-- ==========================================
-- 用户反馈表: 点踩闭环数据收集
-- ==========================================
CREATE TABLE IF NOT EXISTS user_feedback (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL COMMENT '关联任务 ID',
    session_id VARCHAR(128) NOT NULL COMMENT '会话 ID',
    feedback_type VARCHAR(16) NOT NULL COMMENT 'thumbs_up|thumbs_down',
    category VARCHAR(32) DEFAULT NULL COMMENT '结果准确|结果不准确|遗漏风险|误报|其他',
    comment TEXT DEFAULT NULL COMMENT '用户选填文本意见',
    metadata JSON DEFAULT NULL COMMENT '检索文档、相关度分数、系统回答等',
    user_agent VARCHAR(256) DEFAULT NULL,
    source VARCHAR(32) DEFAULT 'review' COMMENT 'review|business_risk',
    trace_id VARCHAR(64) DEFAULT NULL COMMENT '链路追踪 ID, 关联 MDC 日志',
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_feedback_task (task_id),
    INDEX idx_feedback_session (session_id),
    INDEX idx_feedback_type_created (feedback_type, created_at),
    INDEX idx_feedback_trace (trace_id)
);

-- 存量环境升级: user_feedback 增加 trace_id 列
-- ALTER TABLE user_feedback ADD COLUMN trace_id VARCHAR(64) DEFAULT NULL COMMENT '链路追踪 ID, 关联 MDC 日志', ADD INDEX idx_feedback_trace (trace_id);

-- ==========================================
-- Token 用量记录表: LLM 调用真实计量与计费
-- 数据源: Python 层 LLM 响应 usage, 经 RESULT 回调携带落库
-- ==========================================
CREATE TABLE IF NOT EXISTS token_usage_record (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL COMMENT '关联 review_task.task_id',
    submitter VARCHAR(255) COMMENT '计费归属方（无则空串）',
    model VARCHAR(64) COMMENT 'LLM 模型名',
    prompt_tokens INT NOT NULL DEFAULT 0 COMMENT '输入 token 数',
    completion_tokens INT NOT NULL DEFAULT 0 COMMENT '输出 token 数',
    total_tokens INT NOT NULL DEFAULT 0 COMMENT '总 token 数',
    unit_price_snapshot DECIMAL(10,6) COMMENT '单价快照（元/千 token），防止调价后历史账目漂移',
    cost_amount DECIMAL(12,6) COMMENT '本次调用费用 = total_tokens * unit_price_snapshot / 1000',
    created_at TIMESTAMP NOT NULL,
    INDEX idx_usage_task (task_id),
    INDEX idx_usage_submitter (submitter, created_at)
);
