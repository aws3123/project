"""
事故文档生成与种子数据脚本 —— 从真实生产事故数据生成文档目录和种子数据。

这个脚本做什么？
    1. 在本地文件系统中为每个事故创建目录和描述文件
    2. 为每条事故记录生成嵌入向量
    3. 可选地直接写入 ChromaDB（带 --seed 参数时）
    4. 或者导出为 JSON 文件（默认行为）

数据来源：
    REAL_INCIDENTS 列表包含了 70 条真实的公开生产事故记录，
    来源涵盖 Google、AWS、Azure、Cloudflare、GitHub 等公司的公开事后复盘报告。
    每条记录包含：标题、摘要描述、来源ID、所属服务领域、标签列表。

事故分类：
    - Cloud Provider Outages（云服务故障）：如 Google Cloud NPE、AWS DynamoDB DNS 竞态
    - DNS/Network（DNS/网络）：如 GitHub DNS 损坏、Discord 网络故障
    - Database Incidents（数据库事故）：如 PostgreSQL 连接池耗尽、MongoDB 读停顿
    - Kubernetes/Infrastructure（K8s/基础设施）：如控制面过载、网络组件故障
    - Cache Incidents（缓存事故）：如 Redis 驱逐策略不当、缓存雪崩
    - Security/Supply Chain（安全/供应链）：如 npm 包投毒、勒索软件
    - Monitoring/Observability（监控/可观测性）：如告警疲劳、监控盲区
    - Concurrency/Race Conditions（并发/竞态）：如死锁、优先级反转
    - Deployment/CI-CD（部署/持续集成）：如配置错误、重试逻辑缺陷

使用方法：
    # 只生成目录和 JSON 文件
    python -m scripts.generate_incidents

    # 同时写入 ChromaDB
    python -m scripts.generate_incidents --seed
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

# ── 路径设置 ──
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import AppSettings
from repositories.chroma import bootstrap_chromadb, upsert_incident_rows
from repositories.db import _fetch_query_embedding
from repositories.keyword_index import write_keyword_index

# ============================================================
# 真实生产事故数据
# ============================================================
# 每条记录是一个 5 元组：(标题, 摘要描述, 来源ID, 服务领域, 标签列表)
# 所有数据来源于公开的事后复盘报告（postmortem）
#
# 字段说明：
#   - 标题: 简短描述事故（如 "AWS DynamoDB DNS 竞态致 us-east-1 中断 15 小时"）
#   - 摘要: 详细描述根因、影响范围和修复措施
#   - 来源ID: 唯一标识（如 "incident-review-013"）
#   - 服务领域: 所属领域分类（infra=基础设施, saas=SaaS服务, security=安全, ai=AI服务 等）
#   - 标签: 关键词标签列表（如 ["cloud", "dns", "aws"]）
REAL_INCIDENTS: list[tuple[str, str, str, str, list[str]]] = [
    # ── Cloud Provider Outages（云服务故障）──
    (
        "Google Cloud Service Control NPE 致全球中断 7.5 小时",
        "Google Cloud Service Control 服务因空指针异常崩溃，一个包含空白字段的配额策略变更经 Spanner 全球复制后触发新部署代码中的 null 检查缺失。Gmail、Drive、Meet 等 50+ 服务在 40+ 区域中断，Spotify、Discord 等下游亦受影响。根因：新代码无 feature flag 灰度、全局变更缺少验证。",
        "incident-review-013", "infra",
        ["cloud", "null-pointer", "global-outage", "gcp"],
    ),
    (
        "AWS DynamoDB DNS 竞态致 us-east-1 中断 15 小时",
        "DynamoDB 的 DNS 管理存在 TOCTOU 竞态：两个 DNS Enactor 进程竞争执行，一个应用了过期计划，另一个随后删除了「过期」记录，清空了 dynamodb.us-east-1.amazonaws.com 的全部 IP。113 个 AWS 服务级联失败（EC2、Lambda、ECS、EKS），Snapchat、Coinbase、Zoom 等大面积中断。",
        "incident-review-014", "infra",
        ["cloud", "race-condition", "dns", "aws"],
    ),
    (
        "Azure Front Door 配置错误致全球 8 小时中断",
        "Azure Front Door（全球边缘路由/应用交付结构）的一次无意配置变更传播至所有 PoP，影响 DNS 路由、TLS 终止和认证流程。Microsoft 365、Teams、Outlook、Xbox 及 Azure Portal 管理面均不可用。根因：全局边缘配置变更缺少分阶段灰度。",
        "incident-review-015", "infra",
        ["cloud", "config", "global-outage", "azure"],
    ),
    (
        "CrowdStrike 通道文件缺少越界检查致 850 万设备蓝屏",
        "CrowdStrike 通道文件更新时配置数组预期 21 个字段但实际收到 20 个，缺少越界检查导致内核态驱动异常。850 万台 Windows 设备陷入启动循环，全球航空、医疗、应急系统瘫痪，经济损失超 100 亿美元。",
        "incident-review-016", "security",
        ["config", "crash", "global-outage", "qa-miss", "crowdstrike"],
    ),
    (
        "Cloudflare ClickHouse 配置超硬编码限制致 5 小时全局中断",
        "ClickHouse 集群的权限变更导致 Bot Management 特征文件出现重复行，文件体积翻倍超出硬编码的 200 特征上限，代理软件在全球范围返回 HTTP 5xx。1250 万网站受影响，包括 X(Twitter) 和 ChatGPT。",
        "incident-review-017", "infra",
        ["config", "cdn", "global-outage", "cloudflare"],
    ),
    (
        "Fastly CDN 配置错误致全球大量网站 503",
        "CDN 配置变更中一个未验证的边界条件触发全局配置失效，85% 的 Fastly 边缘节点返回 503。多家知名新闻和政府网站瘫痪约 1 小时。根因：缺少配置变更的分阶段上线流程。",
        "incident-review-018", "infra",
        ["cdn", "config", "global-outage"],
    ),
    # ── DNS/Network（DNS/网络）──
    (
        "GitHub DNS 配置损坏致全局不可访问",
        "Puppet 配置管理推送了损坏的 DNS zone 文件，权威 DNS 服务返回 SERVFAIL，全球用户无法解析 github.com。中断约 2 小时。",
        "incident-review-019", "infra",
        ["dns", "config", "global-outage", "github"],
    ),
    (
        "Novu DNS 迁移 NS 记录缓存致 55 分钟中断",
        "DNS 从 Route53 迁移至 Cloudflare 期间部分 ISP 保留了超出 TTL 的旧 NS 记录，部分解析器缓存了 NXDOMAIN 负响应，导致 55 分钟间歇性全局服务中断。",
        "incident-review-020", "infra",
        ["dns", "config", "migration"],
    ),
    (
        "Discord 网络层故障模拟 DDoS 攻击现象",
        "网络层故障导致 TCP 信令期间严重丢包和连接错误，平台呈现类似 DDoS 攻击的故障现象，但无 BGP 路由变更。中断持续数小时，各服务恢复时间不同。",
        "incident-review-021", "infra",
        ["network", "tcp", "connectivity"],
    ),
    # ── Database Incidents（数据库事故）──
    (
        "Coveralls PostgreSQL VACUUM FULL 致连接池耗尽 8 小时",
        "PostgreSQL 维护操作 VACUUM FULL 在历史表上运行超时并超出维护窗口，锁定的表导致后台任务堆积，消耗了全部约 1400 个数据库连接。覆盖上传、报告生成和 CI 工作流全部中断。",
        "incident-review-022", "saas",
        ["database", "postgresql", "connection-pool", "maintenance"],
    ),
    (
        "Matrix.org RAID 故障加 rm 误操作致 24 小时宕机",
        "为 PostgreSQL 主库加磁盘时 RAID 驱动器故障，故障转移至从库时工程师在错误服务器上执行 rm 删除了主库数据目录。两台数据库服务器同时丢失。从 S3 备份恢复 51TB 数据，WAL 回放耗时 5.5 小时。根因：db-01/db-02 命名难以区分主从。",
        "incident-review-023", "infra",
        ["database", "human-error", "backup", "postgresql"],
    ),
    (
        "Slack 数据库维护故障致消息收发中断 9 小时",
        "数据库系统维护操作出现问题，导致流量过载直接冲垮数据库。用户可登录浏览频道但无法发送/接收消息。从网络层面看一切正常（无延迟、无丢包），仅通过综合多维度诊断才定位到数据库层。",
        "incident-review-024", "saas",
        ["database", "maintenance", "outage"],
    ),
    (
        "Onfido 索引变更致级联故障 1.5 小时",
        "数据库迁移删除了核心表上的现有索引并尝试用额外列重建。索引删除导致该表所有操作的 CPU 飙升，索引重建被取消优先级。EU 和 US 区域的 Studio API 和 SDK 持续返回 5xx 错误。",
        "incident-review-025", "saas",
        ["database", "migration", "index", "cascading-failure"],
    ),
    (
        "incident.io PGAudit 扩展锁竞争致数据库 outage",
        "例行的建表加索引迁移触发了 PostgreSQL PGAudit 扩展的意外交互，扩展在持有关键数据库锁时无响应。11 分钟间歇故障后出现 2 分钟完全数据库中断。根因：扩展与 DDL 操作存在锁竞争。",
        "incident-review-026", "saas",
        ["database", "lock-contention", "extension", "postgresql"],
    ),
    (
        "Latitude.sh 控制面损坏致 35 小时数据库集群恢复",
        "站点级故障导致达拉斯区域控制面节点损坏，集群内部状态无法恢复，需要从异地备份完整重建。所有客户数据库停机 35 小时，数据完整但连接 URI、凭据和防火墙规则需重建。根因：控制面快照不够频繁。",
        "incident-review-027", "infra",
        ["database", "control-plane", "backup", "disaster-recovery"],
    ),
    (
        "Kustomer 数据库硬件故障致主从切换延迟",
        "主数据库节点硬件故障触发到从库的切换，时间线渲染服务额外花费 8 分钟重新连接到新主库。90 秒请求失败 + 8 分钟功能降级。",
        "incident-review-028", "saas",
        ["database", "hardware", "failover"],
    ),
    (
        "Kustomer MongoDB 读停顿致 1 小时性能下降",
        "PROD1 环境的数据库读操作短暂停顿（MongoDB），需与 MongoDB 供应商联合调查根因。约 1 小时延迟和性能下降。",
        "incident-review-029", "saas",
        ["database", "mongodb", "performance"],
    ),
    # ── Kubernetes / Infrastructure（K8s/基础设施）──
    (
        "OpenAI 遥测服务压垮 K8s 控制面致 ChatGPT 中断 4 小时",
        "新遥测服务配置导致每个节点同时执行高消耗 K8s API 操作，数千节点瞬间压垮 API Server。DNS 依赖控制面导致缓存过期后服务大规模失败。工程师无法访问已过载的控制面进行修复。",
        "incident-review-030", "ai",
        ["kubernetes", "control-plane", "cascading-failure", "openai"],
    ),
    (
        "SecureAuth Vault 级联故障致全平台 90 分钟 SEV-1",
        "Vault 集群短暂网络断开导致 leader 丢失，依赖服务健康检查失败进入重启循环。K8s HPA 快速扩容使 CockroachDB 连接暴增，Vault 无法恢复。根因：硬依赖 Vault + 无限制自动扩容。",
        "incident-review-031", "infra",
        ["kubernetes", "vault", "cascading-failure", "autoscaling"],
    ),
    (
        "Nebius 网络组件发布致控制面级联故障",
        "内部网络组件的例行发布引发 API 请求暴增，受控降级机制配置错误导致控制面资源失控消耗。VPC 路由失败、BGP 路由撤销、VM 连接丢失、etcd 降级、mk8s 控制面异常。",
        "incident-review-032", "infra",
        ["kubernetes", "network", "cascading-failure", "release"],
    ),
    (
        "DigitalOcean DOKS 配置错误致控制面自动删除",
        "维护期间生产基础设施的错误配置变更触发了托管 K8s 集群控制面资源的自动删除流程。etcd 需从最多 12 小时前的备份恢复，约 9 小时恢复所有 HA 集群。",
        "incident-review-033", "infra",
        ["kubernetes", "config", "control-plane", "data-loss"],
    ),
    (
        "DigitalOcean SFO3 路由器硬件故障致 K8s 网络中断",
        "核心路由器因硬件错误同时重启线卡，数据中心容量减半。网络问题导致 DOKS 集群节点不健康，K8s 控制面连接丢失，节点卡在 Not Ready。约 3 小时恢复。",
        "incident-review-034", "infra",
        ["kubernetes", "hardware", "network", "router"],
    ),
    (
        "systemd-networkd 安全更新致 K8s Pod 网络大规模中断",
        "Ubuntu 安全更新触发 systemd-networkd 自动重启，清除了 CNI 管理的 Pod 间通信路由。Pod 失去网络连通性和 DNS 解析。同一根本原因曾在 BackMarket(2021)、Azure(2022)、Datadog(2023) 重复发生。根因：OS 更新与 K8s 网络交互的隐藏故障模式。",
        "incident-review-035", "infra",
        ["kubernetes", "network", "os-update", "cascading-failure"],
    ),
    # ── Cache Incidents（缓存事故）──
    (
        "Stackademic Redis 驱逐策略致黑五损失 $360K",
        "Redis 驱逐策略配置不当，内存占满时 Redis 驱逐了应用认为始终存在的 key。缓存 miss 暴增 → 数据库过载 → API 宕机，47 分钟损失 $360,000。根因：三名工程师 6 周前已在 Slack 中预警但无人处理。",
        "incident-review-036", "ecommerce",
        ["cache", "redis", "eviction", "config", "financial-loss"],
    ),
    (
        "Box 实验框架冲垮缓存致间歇故障",
        "渐进式功能上线框架将决策结果意外存入中间件缓存，导致缓存被冲垮、频繁驱逐。Web 应用需反复重建高开销数据，延迟恶化。上传、下载、API、Box Sign 和 Box Notes 间歇失败。",
        "incident-review-037", "saas",
        ["cache", "framework", "eviction", "performance"],
    ),
    (
        "Twingate 缓存过期与数据迁移叠加致登录失败",
        "新控制器版本的数据迁移导致两个交互故障：权限全量重新评估 + 迁移未替换缓存值。旧缓存数据数小时后过期才暴露问题，用户无法访问资源。根因：数据迁移未考虑缓存一致性。",
        "incident-review-038", "security",
        ["cache", "migration", "expiration", "inconsistency"],
    ),
    (
        "redirect.pizza 缓存清空致 HTTPS 重定向失败 6 天",
        "新二进制部署清空了内存中的 SSL 证书缓存。重新拉取时对象存储提供商出人意料地将限流提升了 10 倍以上，证书无法加载导致 HTTPS 重定向持续失败。",
        "incident-review-039", "saas",
        ["cache", "ssl", "rate-limit", "deploy"],
    ),
    (
        "Logto JWKS 缓存与签名密钥轮换致认证失败 1 小时",
        "签名密钥被轮换后 logto.io 上的 JWKS 响应仍被缓存。客户端使用陈旧的 JWKS 验证新 Token，全部认证失败。约 60 分钟多个生产租户无法登录。根因：缓存清除与密钥轮换未协调。",
        "incident-review-040", "saas",
        ["cache", "auth", "jwt", "key-rotation"],
    ),
    (
        "imgix 硬件故障致缓存损坏图片未被检测",
        "单台渲染机器硬件故障产生带 artifacts 的图片。因缺少自动检测，损坏图片被缓存后无法被及时发现。EU 区域小部分图片请求质量下降。根因：缺少缓存内容完整性校验。",
        "incident-review-041", "saas",
        ["cache", "hardware", "data-integrity", "image"],
    ),
    # ── Security / Supply Chain（安全/供应链）──
    (
        "Nx pull_request_target 注入致 npm 发布凭证泄露",
        "攻击者利用 GitHub Actions 的 pull_request_target 工作流中 bash 注入漏洞（恶意 PR 标题执行任意代码），窃取了 npm 发布令牌。2,000+ 唯一密钥泄露，Nx 包的恶意版本被发布。根因：PR 标题内容未经检查直接拼接至 echo 命令。",
        "incident-review-042", "infra",
        ["security", "supply-chain", "ci", "github-actions"],
    ),
    (
        "debug/chalk 维护者被钓鱼致 18+ 包投毒",
        "攻击者通过伪装成 npm 官方 2FA 重置的钓鱼邮件获取了主流 npm 包维护者的 npm 凭证。debug、chalk、ansi-styles 等 18+ 包被注入浏览器密窃取恶意代码，恶意版本下载量超 250 万。",
        "incident-review-043", "infra",
        ["security", "supply-chain", "phishing", "npm"],
    ),
    (
        "Shai-Hulud npm 蠕虫自传播致 500+ 包被投毒",
        "首次自传播 npm 蠕虫：窃取维护者 npm 令牌后自动枚举包列表、注入 bundle.js(3.6MB)、重新发布恶意版本。创建 GitHub Actions 工作流窃取 secrets，将私有仓库公开。500+ 包版本被 GitHub 下架。",
        "incident-review-044", "infra",
        ["security", "supply-chain", "worm", "npm"],
    ),
    (
        "PostHog pull_request_target 致 SDK 被投毒 5 小时",
        "攻击者通过 pull_request_target 工作流窃取了 GitHub PAT，利用 PAT 修改工作流、转储 secrets、窃取 npm 发布令牌。多个 SDK 包在 5 小时内被植入恶意 preinstall 脚本。",
        "incident-review-045", "saas",
        ["security", "supply-chain", "ci", "github-actions"],
    ),
    (
        "Polyfill.io 域名控制权交接致百万站点被植入恶意代码",
        "Polyfill.io CDN 域名和 GitHub 组织过期后被攻击者购买。新所有者将恶意 JavaScript 注入 polyfill 库，数百万网站用户受到影响。根因：开源项目域名无续期管理和交接审计。",
        "incident-review-046", "infra",
        ["security", "supply-chain", "cdn", "domain"],
    ),
    (
        "GhostActions PyPI 凭据泄露致 3000+ secrets 被窃",
        "PyPI 维护者账户被攻陷后插入恶意 GitHub Actions 工作流，窃取 3000+ 密钥，其中包括 npm 令牌。跨生态影响严重。",
        "incident-review-047", "infra",
        ["security", "supply-chain", "pypi", "ci"],
    ),
    (
        "Jaguar Land Rover 勒索软件致生产中断超 1 个月",
        "Scattered Lapsus$ Hunters 组织攻击 JLR 数字和生产系统。生产中断超 1 个月，Q2 销量下降约 24%，英国政府提供 15 亿英镑贷款。SOC 估算每周损失超 $6700 万。",
        "incident-review-048", "manufacturing",
        ["security", "ransomware", "production-halt", "financial-loss"],
    ),
    (
        "Oxfam Hong Kong 勒索软件致 55 万人数据泄露",
        "攻击者利用未启用 MFA 的 VPN、未打补丁的旧防火墙和无效的检测措施横向移动，窃取 330GB 数据包括香港身份证、护照副本和信用卡号。根因：安全补丁缺失 + 保留过期个人数据。",
        "incident-review-049", "nonprofit",
        ["security", "ransomware", "data-leak", "mfa"],
    ),
    (
        "MC2 Data 凭据填充加硬编码凭证致 1 亿条记录泄露",
        "攻击者通过凭据填充攻陷开发者账户，发现开发环境中的硬编码生产 API 凭据，构建自定义工具批量导出数据。1 亿条记录暴露，估值下降 38%。",
        "incident-review-050", "saas",
        ["security", "credential-stuffing", "data-leak", "hardcoded-secret"],
    ),
    # ── Monitoring / Observability（监控/可观测性）──
    (
        "PagerDuty Kafka 4.2M 额外生产者未被监控发现",
        "PagerDuty Kafka 集群出现 4.2M 额外生产者（正常值的 84 倍）未被监控发现，直到 JVM 堆耗尽。19 条高紧急告警中 18 条是 webhook 相关，淹没了核心 API 错误的告警。根因：Kafka 生产者和 JVM 堆使用无观测能力。",
        "incident-review-051", "saas",
        ["monitoring", "kafka", "alert-fatigue", "observability"],
    ),
    (
        "Datadog 自身宕机致 2 小时 14 分钟检测延迟",
        "Datadog 后端更新导致竞态条件，丢弃高基数标签用户的 92% 传入指标。内部仪表盘显示指标采集为 0 但无告警触发——告警 100% 依赖 Datadog 自身。切换至 OpenTelemetry 1.20 耗时 72 小时。",
        "incident-review-052", "saas",
        ["monitoring", "observability", "vendor-lock-in", "outage"],
    ),
    (
        "OpenTelemetry filter 误配置致 AI 指标静默丢失 72 小时",
        "Filter processor 中将 include 误配为 exclude，100% 的 AI 工作负载指标被静默丢弃 72 小时。Collector 仅以 debug 级别记录过滤日志（生产环境禁用）。数据科学团队发现而非告警发现。",
        "incident-review-053", "infra",
        ["monitoring", "opentelemetry", "config", "silent-failure"],
    ),
    (
        "Spike.sh Datadog 事件无法自动解决致 2236 个幽灵事件",
        "Datadog 触发的 2236 个事件因聚合逻辑 bug 无法自动解决。分组查询错误地包含了包含状态信息的预格式化消息，导致匹配失败。事件堆积但无人在意。",
        "incident-review-054", "saas",
        ["monitoring", "incident-management", "bug"],
    ),
    (
        "Spike.sh 事件分组错误致 7 客户 26 事件告警失败",
        "分组逻辑更新后一个 latest 布尔标志未被正确设置，7 个客户的 26 个事件被错误分组到同一公开 ID 下，导致告警发送失败。",
        "incident-review-055", "saas",
        ["monitoring", "incident-management", "bug"],
    ),
    (
        "Cloudflare 数据中心电源盲点致 36 小时故障",
        "Flexential 数据中心发电机故障后未通知 Cloudflare。Cloudflare 观测不到数据中心的电源状态——Kafka 和 ClickHouse 等关键服务仅在受影响数据中心运行，团队误以为运行在高可用集群上。",
        "incident-review-056", "infra",
        ["monitoring", "infra", "power-failure", "blind-spot"],
    ),
    # ── Concurrency / Race Conditions（并发/竞态条件）──
    (
        "RavenDB 编译器 bug 引入无锁队列竞态条件",
        "MSVC 编译器在 lock-free 队列的 assembly 输出中添加了意外的额外 load 指令，破坏了线程安全不变量。原始 C 代码和「修复后」代码看似完全相同，但编译器生成了不同汇编。Clang 无此行为。",
        "incident-review-057", "saas",
        ["concurrency", "lock-free", "compiler-bug", "race-condition"],
    ),
    (
        "MySQL 8 INSERT IGNORE 的 gap lock 致并发死锁",
        "从 MySQL 5.7 升级至 8.0.28 后，含唯一键冲突的并发 INSERT IGNORE 触发 supremum 伪记录锁，阻塞全部写入操作。MySQL 团队标记为「符合 InnoDB 合规行为」。",
        "incident-review-058", "infra",
        ["database", "mysql", "deadlock", "upgrade"],
    ),
    (
        "VMware Greenplum 并发 DML 锁升级致死锁",
        "并发事务中的 INSERT 后 UPDATE 操作因锁模式升级（RowExclusiveLock → ExclusiveLock）产生死锁。两个并发事务各自持有低级锁并试图升级时形成循环等待。",
        "incident-review-059", "infra",
        ["database", "deadlock", "concurrency", "lock-upgrade"],
    ),
    (
        "glibc 读写锁优先级反转致实时线程无限自旋",
        "NPTL rwlock 在用户空间自旋时不阻止持有锁的线程被抢占。高优先级实时线程可抢占正在解锁的低优先级线程，然后永远自旋等待锁。一个实时线程自旋了 8 秒。",
        "incident-review-060", "infra",
        ["concurrency", "deadlock", "priority-inversion", "rtos"],
    ),
    (
        "OpenJDK LinkedBlockingQueue 潜在死锁",
        "take() 和 offer() 之间存在潜在死锁：若线程在获取锁与 await() 之间发生上下文切换，并发的 offer() 线程无法获取 takeLock 来 signal 等待线程。已在 OpenJDK 跟踪但难以可靠复现。",
        "incident-review-061", "infra",
        ["concurrency", "deadlock", "jdk", "bug"],
    ),
    # ── Deployment / CI/CD（部署/持续集成）──
    (
        "Slack 数据库维护故障致消息中断 9 小时（2025年2月）",
        "Slack 在 2025 年 2 月中旬遭遇约 9 小时中断，数据库系统维护操作出现问题导致流量过载直接冲垮数据库。用户可登录浏览频道但消息发送/接收完全失败。",
        "incident-review-062", "saas",
        ["deploy", "database", "maintenance", "outage"],
    ),
    (
        "Kameleo 重试逻辑缺陷致 4.0 发布后 503 洪流",
        "4 个月前有意移除了限流，4.0 重新引入时有缺陷的重试逻辑向服务器发送了约 10 倍正常负载。发布回滚后以 1200 req/min 限流 + 健壮重试逻辑重新发布。",
        "incident-review-063", "saas",
        ["deploy", "rate-limit", "retry", "cascading-failure"],
    ),
    (
        "Box API 单系统降级致全 API 503",
        "单个系统的降级产生了不成比例的下游影响，阻塞了所有 API 请求处理。该不健康系统被重新实例化后恢复。承诺建立降级系统的主动检测机制。",
        "incident-review-064", "saas",
        ["deploy", "api", "cascading-failure"],
    ),
    # ── Well-known classics（经典案例，仍有参考价值）──
    (
        "GitLab 数据库目录误删致 18 小时宕机 + 6 小时数据丢失",
        "工程师在恢复主从复制时误在主库执行 rm 删除了数据目录。备份因 pg_dump 版本不匹配长期失效，备份失败通知被 DMARC 拦截。从 6 小时前的 LVM 快照恢复，丢失 issues/merge requests。",
        "incident-review-065", "infra",
        ["database", "human-error", "backup", "data-loss"],
    ),
    (
        "AWS KMS 误操作致大规模服务降级",
        "运维人员在生产环境执行了错误的密钥删除命令，依赖 KMS 加密的 EBS、S3、RDS 等服务无法解密数据。根因：高危操作缺少二次确认。",
        "incident-review-066", "infra",
        ["security", "human-error", "cascading-failure", "aws"],
    ),
    (
        "Fastly CDN 配置错误致全球大量网站 503",
        "CDN 配置变更中未验证的边界条件触发全局失效，85% 边缘节点返回 503。多家知名新闻和政府网站瘫痪。",
        "incident-review-067", "infra",
        ["cdn", "config", "global-outage"],
    ),
    (
        "Mergify 因 GitHub API 对匿名请求返回 403 致服务中断",
        "GitHub API 对匿名请求返回 403 状态码，导致 Mergify 服务启动循环失败。根因：外部 API 变更未做兼容性通知。",
        "incident-review-068", "saas",
        ["api", "dependency", "github", "startup-failure"],
    ),
    (
        "InfluxDB Cloud 健康检查变更致 Vault 过载",
        "健康检查代码变更导致 Vault 过载，Pod 重启风暴。影响 AWS Frankfurt/Oregon/Virginia 区域的写入和读取。",
        "incident-review-069", "infra",
        ["monitoring", "vault", "cascading-failure", "cloud"],
    ),
    (
        "Zalando ElastiCache CPU 80% 致峰值延迟飙升",
        "AWS ElastiCache 在高峰期 CPU 利用率达 80%，导致数据存储延迟飙升。Zalando 通过对数千个 postmortem 的 AI 分析发现配置/部署和容量/扩展问题是数据存储事件的主因。",
        "incident-review-070", "ecommerce",
        ["cache", "redis", "performance", "capacity"],
    ),
    (
        "Piano Composer AU 区域因 Spot 实例回收致服务中断",
        "AWS Spot 实例因流量高峰被回收，节点组容量不足导致 Composer 服务在 AU 区域中断。根因：Spot 实例不适合需要稳定的有状态服务。",
        "incident-review-071", "saas",
        ["cloud", "spot-instance", "capacity", "aws"],
    ),
    (
        "Elasticsearch 升级后节点发现失败致集群不可用",
        "Elasticsearch 集群升级后节点间发现协议不兼容，新节点无法加入集群。写入和查询均不可用，需回滚至旧版本。根因：跳过中间版本的升级路径未经验证。",
        "incident-review-072", "infra",
        ["search", "upgrade", "compatibility", "cluster"],
    ),
    (
        "MongoDB wire protocol 版本不匹配致驱动连接失败",
        "MongoDB 升级后驱动使用的新 wire protocol 版本与服务端不匹配，所有客户端连接失败。根因：驱动升级与服务端升级顺序颠倒。",
        "incident-review-073", "infra",
        ["database", "mongodb", "upgrade", "compatibility"],
    ),
    (
        "Redis 主从切换后数据不一致致缓存雪崩",
        "Redis 哨兵触发主从切换后，新主库因异步复制缺少部分数据。应用读取到空值后回源 DB，数据库瞬间过载。根因：未使用 WAIT 或强一致性配置。",
        "incident-review-074", "ecommerce",
        ["cache", "redis", "consistency", "failover"],
    ),
    (
        "SSL/TLS 证书自动续期失败致 API 全链路 TLS 错误",
        "Let's Encrypt 自动续期因 DNS 验证失败（防火墙规则更改）未更新证书。到期后所有内部和外部 HTTPS 连接失败，全平台不可用约 45 分钟。",
        "incident-review-075", "infra",
        ["network", "tls", "certificate", "automation"],
    ),
    (
        "Helm 回滚失败致 K8s 部署卡在 CrashLoopBackOff",
        "Helm 升级失败后执行 helm rollback，但旧的 manifest 与当前集群状态冲突（资源已变更），回滚 Pod 全部 CrashLoopBackOff。需手动干预删除再重新部署。",
        "incident-review-076", "infra",
        ["kubernetes", "helm", "deploy", "rollback"],
    ),
    (
        "BGP 路由泄露致云服务商 IP 被黑洞路由",
        "某 ISP 错误地通告了云服务商的 IP 前缀，BGP 路由传播导致目标 IP 在全球部分区域被黑洞。多个云服务 30 分钟不可达。",
        "incident-review-077", "infra",
        ["network", "bgp", "routing", "cloud"],
    ),
    (
        "AWS 巴黎区域变压器故障致可用区断电",
        "EU-west-3 区域数据中心主变压器故障导致部分可用区断电，大量实例和服务不可用。备用发电机启动延迟加剧影响。",
        "incident-review-078", "infra",
        ["infra", "power-failure", "aws", "datacenter"],
    ),
    (
        "AWS 东京可用区冷却系统故障致服务器过热关机",
        "冷却系统故障导致服务器温度超标触发硬件保护关机。根因：冷却系统无冗余和实时监控。",
        "incident-review-079", "infra",
        ["infra", "hardware", "cooling", "aws"],
    ),
    (
        "OpenAI API/ChatGPT 因 K8s 控制面过载中断",
        "新遥测服务部署导致数千节点同时执行高消耗 API 操作，K8s API Server 过载。DNS 缓存提供约 20 分钟过期解析后大规模失败。根因：新服务的 API 调用模式未经容量评估。",
        "incident-review-080", "ai",
        ["kubernetes", "control-plane", "cascading-failure", "capacity"],
    ),
    (
        "npm 公钥基础设施变更致 CI 流水线大面积失败",
        "npm 更新了包签名公钥，但旧公钥在 CI 环境被硬编码。大量 CI 流水线在包完整性校验步骤失败，阻塞了所有依赖 npm 的部署流程。",
        "incident-review-081", "infra",
        ["supply-chain", "ci", "npm", "key-rotation"],
    ),
    (
        "GitHub Actions runner 磁盘空间耗尽致 CI 失败",
        "GitHub 托管 runner 的临时存储被大量构建缓存填满，新构建任务因磁盘不足失败。持续约 3 小时，全球 CI 流水线受阻。",
        "incident-review-082", "infra",
        ["ci", "disk-full", "github-actions"],
    ),
]


def main() -> None:
    """脚本入口：创建事故文档目录，生成种子数据。

    两种运行模式：
    1. 默认模式：创建文档目录 + 导出 JSON 文件
    2. --seed 模式：创建文档目录 + 直接写入 ChromaDB
    """
    settings = AppSettings()

    # ── 第 1 步：创建事故文档目录 ──
    # 每个事故一个子目录，里面包含 description.txt 描述文件
    docs_dir = Path(settings.incident_docs_dir)
    # mkdir(parents=True, exist_ok=True):
    #   parents=True → 自动创建不存在的父目录
    #   exist_ok=True → 目录已存在时不报错
    docs_dir.mkdir(parents=True, exist_ok=True)

    # enumerate(REAL_INCIDENTS, start=1) 同时获取索引（从1开始）和值
    for i, (title, snippet, source, service, tags) in enumerate(REAL_INCIDENTS, start=1):
        # zfill(3) 把数字补零到3位：1→"001", 13→"013"
        seq = str(i).zfill(3)
        doc_subdir = docs_dir / f"incident-{seq}"
        doc_subdir.mkdir(parents=True, exist_ok=True)

        # 创建描述文件（如果不存在的话，避免覆盖已有内容）
        desc = doc_subdir / "description.txt"
        if not desc.exists():
            desc.write_text(
                f"标题: {title}\n"
                f"来源: {source}\n"
                f"服务: {service}\n"
                f"标签: {', '.join(tags)}\n\n"
                f"描述:\n{snippet}\n",
                encoding="utf-8",
            )

    print(f"Created {len(REAL_INCIDENTS)} incident directories in {docs_dir}")

    # ── 第 2 步：构建种子数据行 ──
    rows = []
    for title, snippet, source, service, tags in REAL_INCIDENTS:
        try:
            # 为每条事故生成嵌入向量
            embedding = _fetch_query_embedding(snippet, settings=settings)
        except Exception as e:
            # 嵌入失败时不中断，用全零向量占位
            print(f"  [SKIP] Embedding failed for '{title[:30]}...': {e}")
            embedding = [0.0] * 1536  # 1536 维零向量（占位符）

        rows.append({
            "id": f"{source}:{title}",
            "title": title,
            "snippet": snippet,
            "source": source,
            "service": service,
            "tags": tags,
            "embedding": embedding,
            "image_urls": [],
            "image_texts": [],
        })

    # ── 第 3 步：写入数据 ──
    if "--seed" in sys.argv and rows:
        # --seed 模式：直接写入 ChromaDB + ES 关键词索引
        print(f"\nSeeding {len(rows)} incidents to ChromaDB at {settings.chroma_path} ...")
        bootstrap_chromadb(settings)          # 初始化 ChromaDB
        upsert_incident_rows(rows, settings=settings)  # 写入向量数据
        write_keyword_index(rows, settings)   # 写入关键词索引
        print("Done.")
    else:
        # 默认模式：导出为 JSON 文件（用户可以检查后再手动导入）
        output = ROOT / "data" / "incidents.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        json_rows = []
        for title, snippet, source, service, tags in REAL_INCIDENTS:
            json_rows.append({
                "title": title,
                "snippet": snippet,
                "source": source,
                "service": service,
                "tags": tags,
            })
        output.write_text(json.dumps(json_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {len(json_rows)} incidents to {output}")
        print("Run with --seed to also push to ChromaDB.")


if __name__ == "__main__":
    main()
