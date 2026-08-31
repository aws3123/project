---
name: context7
description: "Use the ctx7 CLI to fetch up-to-date library documentation. Activate when writing code with libraries/frameworks, verifying API signatures, or when training data may be outdated."
---

# Context7 — 实时文档查询

使用 ctx7 CLI 获取任意库/框架的最新文档，避免使用过时 API。

## 核心用法

### 查询文档（两步走）

```bash
# Step 1: 解析库 ID
ctx7 library <name> <query>

# Step 2: 获取文档
ctx7 docs <libraryId> <query>
```

**示例：**
```bash
# 查 Spring Boot 配置相关文档
ctx7 library "spring boot" configuration
ctx7 docs /spring-projects/spring-boot "externalized configuration"

# 查 LangGraph 状态管理
ctx7 library langgraph state
ctx7 docs /langchain-ai/langgraph "state management"

# 查 React hooks
ctx7 library react hooks
ctx7 docs /facebook/react "hooks rules"
```

### 常见错误

- 库 ID 需要 `/` 前缀 — 用 `/facebook/react` 而不是 `facebook/react`
- 必须先跑 `ctx7 library` 获取有效 ID — 直接 `ctx7 docs react "hooks"` 会失败
- 查询用英文效果更好

### 技能管理

```bash
ctx7 skills search <keywords>    # 搜索技能注册表
ctx7 skills suggest              # 根据项目依赖自动推荐
ctx7 skills list                 # 列出已安装技能
ctx7 skills install /owner/repo  # 从 GitHub 安装技能
ctx7 skills remove <name>        # 卸载技能
```

## 何时使用

- 编写涉及不熟悉的库/框架的代码时
- 验证 API 签名或方法参数时
- 模型训练数据可能过时时（如新版本 breaking changes）
- 用户明确要求查阅文档时

## 何时不使用

- 查询项目自身代码（直接读文件）
- 通用编程知识（如语法、算法）
- 已有记忆/规范明确回答的问题
