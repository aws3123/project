# Frontend

## 模块定位
前端使用 React + Vite + TypeScript，负责 AI Code Review Sentinel 的页面展示与交互。

当前页面入口：
- `/`：提交审查
- `/tasks`：查看当前会话任务列表
- `/tasks/:taskId`：查看任务详情、状态时间线、人工复核与节点日志
- `/results/:taskId`：查看同步结果与风险摘要

## 开发命令
在仓库根目录执行：

```bash
pnpm --dir frontend install
pnpm --dir frontend dev
pnpm --dir frontend build
pnpm --dir frontend vitest run src/tests/submitForm.test.tsx src/pages/SubmitPage.test.tsx src/pages/TaskDetailPage.test.tsx
```

## 本轮任务台改造范围
第一轮仅改造任务台相关页面，视觉方向高度参考 GitHub。

In scope：
- `TaskDashboardPage`
- `TaskDetailPage`
- `ResultDetailPage`
- `ReviewResultCard`
- `TaskStatusBadge`
- `LogsPanel`
- `ReportDownloadButton`

Out of scope：
- `SubmitPage` / `ReviewSubmitForm` 结构重做
- `router / api / store / hooks` 行为契约变更
- dark mode
- 搜索、筛选、分页等新功能
