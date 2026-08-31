# Superpowers — Qoder Plugin

AI 编程代理技能框架与软件开发方法论。

## 来源

- **原始仓库**: https://github.com/obra/superpowers
- **作者**: Jesse Vincent (obra) / Prime Radiant
- **协议**: MIT

## 包含技能 (14 个)

### 协作与流程
| 技能 | 用途 |
|---|---|
| `brainstorming` | 需求澄清与设计探索，苏格拉底式提问 |
| `writing-plans` | 将设计拆解为细粒度实施计划（每任务 2-5 分钟） |
| `executing-plans` | 分批执行计划，带人工检查点 |
| `dispatching-parallel-agents` | 并发子代理工作流 |
| `subagent-driven-development` | 快速迭代 + 两阶段审查（规范合规 + 代码质量） |

### 代码审查
| 技能 | 用途 |
|---|---|
| `requesting-code-review` | 发起代码审查，含预审查清单 |
| `receiving-code-review` | 响应审查反馈 |

### 测试与调试
| 技能 | 用途 |
|---|---|
| `test-driven-development` | RED-GREEN-REFACTOR 循环 |
| `systematic-debugging` | 4 阶段根因分析流程 |
| `verification-before-completion` | 确认问题真正修复 |

### Git 与分支
| 技能 | 用途 |
|---|---|
| `using-git-worktrees` | 并行开发分支（worktree 隔离） |
| `finishing-a-development-branch` | 合并/PR 决策工作流 |

### 元技能
| 技能 | 用途 |
|---|---|
| `using-superpowers` | 技能系统入口，自动触发相关技能 |
| `writing-skills` | 创建新技能的指南 |

## 核心工作流

```
brainstorming → writing-plans → subagent-driven-development → requesting-code-review → finishing-a-development-branch
```

## 安装位置

项目级插件：`.qoder/plugins/superpowers/`

## 未包含

- Visual Companion 服务器脚本（brainstorming/scripts/ 中的 Node.js 服务）— 需要浏览器环境，保留文件但未配置自动启动
- 平台特定引用（Codex/Pi/Antigravity 工具引用）— 不适用于 Qoder
