# 点踩反馈闭环 — 设计文档

## 概述

在 MVP 阶段后，系统缺少持续优化依据。本设计搭建"收集→分析→优化→验证"数据闭环：前端点踩功能携带检索上下文落库，为 Prompt 迭代和检索策略调整提供数据支撑。

目标指标：k6 模拟 200 并发用户同时提交反馈 3 分钟，反馈落库成功率 99.5%+，P99 写入延迟 < 120ms。

## 架构总览

```
前端 TaskDetailPage
  └─ FeedbackWidget (thumbs up/down + 选填评论 + 分类)
       │ POST /api/feedback/submit
       ▼
Java FeedbackController
  └─ FeedbackService → FeedbackMapper → MySQL: user_feedback 表
       │
       └─ GET /api/feedback/stats + /api/feedback/export
              └─ Python 端拉取用于"分析→优化"管道
```

## 数据库表

```sql
CREATE TABLE user_feedback (
  id             BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_id        VARCHAR(64)  NOT NULL,
  session_id     VARCHAR(128) NOT NULL,
  feedback_type  VARCHAR(16)  NOT NULL COMMENT 'thumbs_up|thumbs_down',
  category       VARCHAR(32)  DEFAULT NULL COMMENT '结果准确|结果不准确|遗漏风险|误报|其他',
  comment        TEXT         DEFAULT NULL,
  metadata       JSON         DEFAULT NULL COMMENT '含 retrievedDocs, relevanceScores, systemAnswer 等',
  user_agent     VARCHAR(256) DEFAULT NULL,
  source         VARCHAR(32)  DEFAULT 'review' COMMENT 'review|business_risk',
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_feedback_task (task_id),
  INDEX idx_feedback_session (session_id),
  INDEX idx_feedback_type_created (feedback_type, created_at)
);
```

## Java 后端

### 新增文件

| 文件 | 说明 |
|------|------|
| `entity/UserFeedback.java` | MyBatis-Plus 实体，字段映射上表 |
| `repository/mapper/FeedbackMapper.java` | BaseMapper + 自定义查询方法 |
| `service/FeedbackService.java` | 提交校验 + 幂等处理 + 落库 |
| `controller/FeedbackController.java` | REST 端点 |

### API 端点

**`POST /api/feedback/submit`** — 提交反馈
- 请求体：`{ taskId, sessionId, feedbackType, category?, comment?, metadata?, source? }`
- 响应 201：`{ id, status: "accepted" }`
- 幂等：同一 `taskId` + `sessionId` + `feedbackType` 更新已有记录（保留最近一次）
- 校验：`feedbackType` enum，`taskId` 必填

**`GET /api/feedback/stats`** — 统计面板（供 Python 读取）
- 参数：`from`, `to`, `source?`
- 返回：`{ total, thumbsUp, thumbsDown, ratio, dailyBreakdown[] }`

**`GET /api/feedback/export`** — 导出明细
- 参数：`from`, `to`, `source?`, `page?`, `size?`
- 返回：分页反馈记录列表

## 前端

### 新增/修改文件

| 文件 | 说明 |
|------|------|
| `types/feedback.ts` | 类型定义：`FeedbackType`, `FeedbackCategory`, `FeedbackSubmitRequest`, `FeedbackState` |
| `api/feedback.ts` | `submitFeedback()` 函数，通过 `http<T>()` 调用 POST /api/feedback/submit |
| `components/FeedbackWidget.tsx` | 点踩组件：thumbs up/down 按钮 → 分类选择 → 文本输入 → 提交 |
| `pages/TaskDetailPage.tsx` | 在 `ReviewResultCard` 下方嵌入 `<FeedbackWidget />`，传入 task/result 数据 |

### FeedbackWidget 交互

1. 初始状态：显示 thumbs up / thumbs down 两个按钮
2. 点击一个按钮 → 该按钮高亮，弹出分类选择器 + 文本输入框 + 提交按钮
3. 提交成功 → 按钮置灰，显示"感谢反馈！"
4. 自动收集 metadata：`systemAnswer` = `result.riskSummary + result.details`
5. 幂等：已提交过的 taskId 自动置灰

## Python 端（分析管道，远期规划）

本次不实现完整的分析管道，仅在 Java 端开放统计和导出 API。
后续 Python 端可：
- 定时读取 `GET /api/feedback/export`，聚合反馈数据
- 分析 thumbs down 高频分类，驱动 Prompt 模板调整
- 关联检索文档和相关度分数，优化检索策略

## 测试

| 层 | 范围 |
|----|------|
| Java 单元 | `FeedbackServiceTest` — 校验逻辑、幂等、边界 |
| Java 集成 | `FeedbackControllerTest` — API 请求/响应、错误码 |
| 前端组件 | `FeedbackWidget.test.tsx` — 交互状态、提交流程 |
| 前端 API | MSW handler + `submitFeedback` 测试 |
| 压测 | `k6/feedback-submit.js` — 200 并发 3 分钟 |

## 性能目标

- 200 并发用户持续 3 分钟提交反馈
- 落库成功率 ≥ 99.5%
- P99 写入延迟 ≤ 120ms
