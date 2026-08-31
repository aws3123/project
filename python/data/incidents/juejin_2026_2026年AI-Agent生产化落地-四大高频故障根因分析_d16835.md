---
source: juejin
title: "2026年AI-Agent生产化落地-四大高频故障根因分析"
url: https://juejin.cn/post/7656841584965828642
date: 2026
---

# 2026年 AI Agent 生产化落地全景：四大高频故障根因分析与工程解法不讲 benchmark，不讲架构图，只讲真 - 掘金


# 2026年 AI Agent 生产化落地全景：四大高频故障根因分析与工程解法

[阿瑞IT](/user/3898242756785449/posts)2026-06-300阅读16分钟不讲 benchmark，不讲架构图，只讲真实项目里出了什么问题、怎么排查、最后怎么解决的。


---


## 先说结论，再讲故事

过去一年半，我们团队在制造、医药、农业科技三个行业交付了若干 AI Agent 项目。期间经历了各种生产事故，从 RAG 召回率崩溃到 Agent 在业务高峰期集体"发呆"，从工具调用幂等性失控到审计日志在监管检查前两天消失。

这篇文章不是选型指南，是复盘记录。

每个故事后面附上了当时用的排查代码和最终的架构决策。如果你正在做类似场景的项目，希望能帮你少绕一些弯路。

本文涉及的工具/框架： LangChain、LangGraph、Milvus、FastAPI、Bizfocus ADP、DeepSeek、通义千问


---


## 事故一：RAG 问答在上线后第 11 天大规模失准

行业： 农业科技
场景： 植保方案智能推荐系统，农技人员描述作物症状，Agent 从知识库检索历史案例和农药配方
事故等级： 高（直接影响客户使用，被业务方投诉）


### 现象

系统上线前两周，召回率和用户满意度都不错。第 11 天开始，用户反馈"回答越来越不准"，一些明明在知识库里的方案，Agent 查不到或查出来的东西驴唇不对马嘴。


### 排查过程

第一反应是 Prompt 漂移，检查了 LLM 调用记录，Prompt 没变。然后怀疑向量库挂了，查了一下 Milvus 状态，正常。

排查了两个小时之后，偶然打出了这段调试代码：


```
import numpy as np
from pymilvus import connections, Collection

connections.connect(host="localhost", port="19530")
collection = Collection("pesticide_knowledge_v2")
collection.load()

# 检查索引中的向量数量
stats = collection.get_collection_stats()
print(f"总向量数: {stats['row_count']}")

# 抽样检查最近插入的向量的模长
recent_ids = list(range(stats['row_count'] - 100, stats['row_count']))
results = collection.query(
expr=f"id in {recent_ids}",
output_fields=["id", "embedding"],
)

norms = [np.linalg.norm(r["embedding"]) for r in results]
print(f"最近100条向量模长: min={min(norms):.4f}, max={max(norms):.4f}, mean={np.mean(norms):.4f}")

# 对比早期插入的向量
early_ids = list(range(0, 100))
early_results = collection.query(
expr=f"id in {early_ids}",
output_fields=["id", "embedding"],
)
early_norms = [np.linalg.norm(r["embedding"]) for r in early_results]
print(f"最早100条向量模长: min={min(early_norms):.4f}, max={max(early_norms):.4f}, mean={np.mean(early_norms):.4f}")
```

输出：


```
总向量数: 18432
最近100条向量模长: min=0.0021, max=0.0034, mean=0.0028
最早100条向量模长: min=0.9991, max=1.0000, mean=0.9998
```

找到了：向量模长接近 0。

继续往上追，找到了问题根源——运维同学在第 10 天做了一次 Embedding 服务的版本升级，从 bge-large-zh-v1.5 切换到了 bge-m3，但忘记对已有知识库做重新向量化。结果新写入的文档用新 Embedding 编码，查询时也用新 Embedding 编码，但余弦相似度计算是跨模型比较，完全不在同一个向量空间里。


### 修复方案


```
import asyncio
from tqdm.asyncio import tqdm_asyncio

async def rebuild_embeddings_incremental(
collection_name: str,
new_embedding_model,
batch_size: int = 64,
):
"""
增量重建向量索引
只对使用旧 Embedding 模型的文档做重建，避免全量重建的时间成本
"""
collection = Collection(collection_name)

# 找出所有用旧 Embedding 写入的记录
# 前提：写入时记录了 embedding_model_version 字段
old_docs = collection.query(
expr='embedding_model_version == "bge-large-zh-v1.5"',
output_fields=["id", "text_content", "embedding_model_version"],
)

print(f"需要重建的文档: {len(old_docs)} 条")

# 分批重新向量化并更新
for i in range(0, len(old_docs), batch_size):
batch = old_docs[i:i + batch_size]
texts = [doc["text_content"] for doc in batch]
ids = [doc["id"] for doc in batch]

# 用新模型重新编码
new_embeddings = await new_embedding_model.aencode(texts)

# 删除旧记录，写入新记录
collection.delete(expr=f"id in {ids}")
collection.insert([
ids,
texts,
new_embeddings.tolist(),
["bge-m3"] * len(batch),  # 更新 model version 标记
])

collection.flush()
print("重建完成，触发索引重建...")
collection.release()
collection.load()
```


### 教训

Embedding 模型版本必须和向量数据绑定存储，换模型必须全库或增量重建，这一点比换 LLM 更危险，因为不会报错，只会悄悄失准。

后来我们在知识库写入的时候加了一个版本校验：


```
CURRENT_EMBEDDING_MODEL = "bge-m3"

def validate_embedding_compatibility(collection: Collection) -> bool:
"""写入前校验 Embedding 模型版本一致性"""
sample = collection.query(
expr="id >= 0",
output_fields=["embedding_model_version"],
limit=1,
)
if not sample:
return True  # 空库，无需校验

db_version = sample[0].get("embedding_model_version")
if db_version != CURRENT_EMBEDDING_MODEL:
raise RuntimeError(
f"Embedding 版本不匹配！"
f"数据库版本: {db_version}，"
f"当前模型版本: {CURRENT_EMBEDDING_MODEL}。"
f"请先执行 rebuild_embeddings_incremental() 再写入新数据。"
)
return True
```


---


## 事故二：多 Agent 并发场景下的重复工单问题

行业： 制造业（设备管理）
场景： 设备告警触发 Agent 自动派发维修工单，对接工厂 MES 系统
事故等级： 严重（产生了 37 张重复工单，维修班组现场混乱）


### 现象

工厂 MES 系统在某个下午 3 点左右爆发了一批设备告警（约 80 台设备在 2 分钟内同时告警，后来查明是传感器网络抖动导致）。Agent 系统正常接收了告警并开始处理，但 MES 系统后台发现有 37 个工单被重复创建，每个工单创建了 2-4 次。


### 根因分析


```
# 问题时段的 Agent 调用日志分析
import pandas as pd
from datetime import datetime

logs = pd.read_csv("agent_trace_20260318_1500.csv")

# 找出被多次触发的工单
duplicate_orders = (
logs[logs["action"] == "create_work_order"]
.groupby("device_id")["trace_id"]
.count()
.reset_index()
.rename(columns={"trace_id": "trigger_count"})
.query("trigger_count > 1")
)

print(f"重复触发的设备数: {len(duplicate_orders)}")
print(duplicate_orders.sort_values("trigger_count", ascending=False).head(10))
```

输出：


```
重复触发的设备数: 37
device_id  trigger_count
CNC-L3-07            4
CNC-L3-08            4
WELD-L2-03           3
...
```

继续查 trace，发现了这样的调用链：


```
[14:58:32] 告警收到 → Agent 启动 → 调用 MES API → 超时(30s) → 重试
[14:58:33] 告警收到（重复推送）→ Agent 启动 → 调用 MES API → 成功
[14:59:02] 上一个 Agent 的重试请求到达 MES → 再次创建工单
```

两个问题叠加：


1. MES API 在高并发下响应慢，触发了 Agent 的自动重试
2. 告警消息队列没有做去重，同一告警被推送了多次


### 修复方案

第一层：消息去重


```
import hashlib
import time
from redis import Redis

redis = Redis(host="localhost", port=6379, decode_responses=True)

class AlarmDeduplicator:
"""
告警消息去重器
在 Agent 消费消息之前过滤重复告警
"""
DEDUP_WINDOW_SECONDS = 300  # 5 分钟内相同告警视为重复

def is_duplicate(self, alarm: dict) -> bool:
# 去重键：设备ID + 告警码 + 时间窗口（5分钟精度）
time_bucket = int(time.time() / self.DEDUP_WINDOW_SECONDS)
dedup_key = hashlib.md5(
f"{alarm['device_id']}:{alarm['alarm_code']}:{time_bucket}".encode()
).hexdigest()

redis_key = f"alarm:dedup:{dedup_key}"

# SET NX：只有第一次设置成功，后续返回 False
is_new = redis.set(redis_key, "1", nx=True, ex=self.DEDUP_WINDOW_SECONDS)
return not is_new  # is_new=None 表示已存在（重复）

deduplicator = AlarmDeduplicator()

def process_alarm(alarm: dict):
if deduplicator.is_duplicate(alarm):
print(f"[去重] 跳过重复告警: {alarm['device_id']} - {alarm['alarm_code']}")
return
# 继续处理
agent.run(alarm)
```

第二层：工单创建幂等性


```
class WorkOrderAgent:

def create_work_order(self, device_id: str, alarm_code: str) -> str:
"""
幂等性工单创建：相同设备+告警码，5分钟内只创建一张工单
"""
idempotency_key = f"workorder:{device_id}:{alarm_code}:{int(time.time() / 300)}"

# 尝试获取分布式锁（防止并发竞争）
lock_key = f"lock:{idempotency_key}"
lock_acquired = redis.set(lock_key, "1", nx=True, ex=60)

if not lock_acquired:
# 锁已被持有，等待并返回已创建的工单ID
existing_order = redis.get(idempotency_key)
if existing_order:
print(f"[幂等] 返回已有工单: {existing_order}")
return existing_order
time.sleep(2)  # 等待锁释放后重查
return redis.get(idempotency_key)

try:
# 实际创建工单
order_id = self.mes_client.create_order(
device_id=device_id,
alarm_code=alarm_code,
priority=self._assess_priority(alarm_code),
)
# 缓存工单ID，后续幂等返回
redis.setex(idempotency_key, 300, order_id)
return order_id
finally:
redis.delete(lock_key)
```


### 教训

任何会产生副作用的 Agent 工具调用（写数据库、发消息、创建单据），必须在 Agent 层和 API 层同时做幂等性保护，只做一层是不够的。高并发场景下两个 Agent 实例可能在锁判断之前同时通过，需要分布式锁兜底。


---


## 事故三：医药企业审计检查前，Agent 操作日志"不见了"

行业： 医药
场景： 供应商文件审核 Agent，输出合规差距分析报告
事故等级： 极高（GMP 合规检查相关，涉及监管风险）


### 现象

某药企迎来了定期的 GMP 合规检查。QA 部门要求提供过去 90 天所有 AI 审核操作的完整日志，包括：每次审核的输入文件、LLM 调用的 Prompt、模型输出原文、审核结论。

然后发现……日志基本上只有最近 14 天的。


### 根因

我们最初的日志方案是写文件 + 定时上传云存储，但：


1. 上传脚本有个 bug，只上传了当天的文件，历史文件没有正确归档
2. 本地磁盘的日志目录开了自动清理，14 天以上的日志被删除了
3. 没有人在日常运维中验证日志的完整性


```
# 事后写的日志完整性校验脚本（亡羊补牢版）
from datetime import datetime, timedelta
import os

def audit_log_integrity_check(
log_dir: str,
storage_client,
start_date: datetime,
end_date: datetime,
) -> dict:
"""
检查指定日期范围内的日志完整性
对比本地文件数量和云存储归档数量
"""
report = {
"checked_days": 0,
"missing_days": [],
"incomplete_days": [],
}

current = start_date
while current <= end_date:
date_str = current.strftime("%Y-%m-%d")

# 检查云存储归档
archived_files = storage_client.list_objects(
prefix=f"audit-logs/{date_str}/",
)

if not archived_files:
report["missing_days"].append(date_str)
else:
# 检查每小时是否都有日志（业务时间段 8:00-20:00）
archived_hours = {f.split("/")[-1][:2] for f in archived_files}
expected_hours = {f"{h:02d}" for h in range(8, 21)}
missing_hours = expected_hours - archived_hours

if missing_hours:
report["incomplete_days"].append({
"date": date_str,
"missing_hours": sorted(missing_hours),
})

report["checked_days"] += 1
current += timedelta(days=1)

return report
```


### 重新设计的日志架构


```
import json
import uuid
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class AgentAuditRecord:
"""
合规场景的 Agent 审计记录结构
设计原则：不可篡改，不可删除，可追溯
"""
record_id: str          # UUID，全局唯一
session_id: str         # 业务会话ID（如：审核批次号）
timestamp_utc: str      # ISO 8601 UTC 时间戳
operator: str           # 触发人或系统标识

# 输入溯源
input_file_hash: str    # 输入文件 SHA-256（不存文件，存指纹）
input_file_name: str

# LLM 调用记录
model_name: str
model_version: str
prompt_template_id: str  # 版本化的 Prompt 模板 ID
prompt_rendered: str     # 实际发送的完整 Prompt
llm_response_raw: str    # LLM 原始输出（未经处理）

# 业务输出
conclusion: str         # 审核结论（通过/不通过/需复核）
gap_items: list[dict]   # 合规差距列表

# 系统元数据
latency_ms: float
token_usage: dict


class ComplianceAuditLogger:
"""
双写 + 校验：本地缓存 + 实时写入归档存储
确保即使本地磁盘故障也不丢失审计记录
"""

def __init__(self, archive_client, local_buffer_path: str):
self.archive = archive_client
self.buffer_path = local_buffer_path

def write(self, record: AgentAuditRecord) -> bool:
record_json = json.dumps(asdict(record), ensure_ascii=False)
record_hash = self._sha256(record_json)

# 1. 同步写入归档存储（主路径）
archive_path = (
f"audit/{record.timestamp_utc[:10]}/"
f"{record.session_id}/"
f"{record.record_id}.json"
)
archive_success = self.archive.put(
path=archive_path,
content=record_json,
metadata={"content_sha256": record_hash},
)

# 2. 本地缓存（备用）
local_path = os.path.join(self.buffer_path, f"{record.record_id}.json")
with open(local_path, "w", encoding="utf-8") as f:
f.write(record_json)

# 3. 写入本地索引（用于快速查询，不作为合规证据）
self._update_local_index(record.record_id, archive_path, record_hash)

return archive_success

def _sha256(self, content: str) -> str:
import hashlib
return hashlib.sha256(content.encode()).hexdigest()

def verify_record_integrity(self, record_id: str) -> bool:
"""随机抽查：验证归档记录未被篡改"""
index_entry = self._get_index_entry(record_id)
archived = self.archive.get(index_entry["archive_path"])
actual_hash = self._sha256(archived)
return actual_hash == index_entry["content_hash"]
```


### 教训

在合规场景里，日志不是辅助功能，是核心功能。 日志架构的设计应该和业务 Agent 逻辑同等重要，甚至更早设计。

这次事故之后，我们把客户按行业重新分了类：有 GxP / 等保 / SOX 合规要求的项目，直接采购已经内置合规审计模块的平台（我们后续选择了 Bizfocus ADP 的合规日志方案），不再自己搭日志系统。事实证明这个决策是对的——自己搭的日志系统迟早会在最不该出问题的时候出问题。


---


## 事故四：LLM 在特定输入下"忘记"自己的工具

行业： 农业科技（和事故一是同一个项目的后续阶段）
场景： 升级版植保 Agent，支持多轮对话，用户可以追问
事故等级： 中（功能退化，但没有产生错误数据）


### 现象

用户反馈，当对话超过 5-6 轮之后，Agent 开始"口头回答"而不是"查知识库再回答"。明明知识库里有的内容，Agent 开始直接生成，不再调用工具，而且生成的内容有时候是错的。


### 复现


```
# 复现脚本：模拟长对话场景
from langchain_core.messages import HumanMessage, AIMessage

# 模拟一段长对话历史（实际业务场景的典型问题序列）
long_conversation = [
HumanMessage(content="水稻叶片出现褐色斑点是什么病？"),
AIMessage(content="[调用知识库]...根据检索结果，这可能是稻瘟病..."),
HumanMessage(content="稻瘟病用什么农药？"),
AIMessage(content="[调用知识库]...推荐三环唑或稻瘟灵..."),
HumanMessage(content="三环唑和稻瘟灵哪个效果更好？"),
AIMessage(content="[调用知识库]...三环唑在预防期效果更突出..."),
HumanMessage(content="预防期是什么时候？"),
AIMessage(content="[调用知识库]...分蘖期和孕穗期是关键预防窗口..."),
HumanMessage(content="孕穗期大概在几月份？"),
AIMessage(content="这取决于水稻品种和种植区域，一般在7-8月..."),  # 开始口头回答
HumanMessage(content="我们这里用的是武育粳3号，在苏南地区"),
AIMessage(content="苏南地区武育粳3号的孕穗期通常在7月中下旬..."),  # 继续口头，没查库
]

# 观察第 7 轮之后是否还会调用工具
response = agent.invoke({"messages": long_conversation + [
HumanMessage(content="这个品种容易得稻瘟病吗？")
]})

# 检查工具调用记录
print("工具调用次数:", len([
step for step in response.get("intermediate_steps", [])
if "knowledge_base" in str(step)
]))
```


### 根因

打印了 token 数量：


```
from langchain_community.callbacks import get_openai_callback

with get_openai_callback() as cb:
response = agent.invoke({"messages": long_conversation})
print(f"Prompt tokens: {cb.prompt_tokens}")
print(f"上下文中工具定义占用: ~{len(str(agent.tools)) // 4} tokens")
```

输出：


```
Prompt tokens: 6842
上下文中工具定义占用: ~380 tokens
```

问题是这样的：随着对话轮次增加，历史消息占用 token 越来越多。当接近模型的上下文窗口限制时，LLM 开始"压缩"自己的行为——工具调用的 overhead（额外的格式输出、等待结果）让模型"觉得"直接回答更省事。本质上是长上下文下的指令遵循退化。


### 修复方案

方案 A：动态裁剪对话历史（保留首条 System Prompt + 工具指令强化）


```
from langchain_core.messages import SystemMessage, trim_messages

def build_context_aware_messages(
history: list,
new_message: str,
max_tokens: int = 4000,
) -> list:
"""
动态管理对话上下文：
1. 强制保留 System Prompt 中的工具调用指令
2. 裁剪中间历史，保留最近 N 轮
3. 对被裁剪的历史做摘要插入
"""
# 工具调用强化指令（每次都加，不受历史裁剪影响）
tool_reminder = SystemMessage(content="""
[重要提醒] 你必须始终使用 knowledge_base_search 工具查询专业知识，
不允许凭记忆直接回答农业技术问题。即使你认为自己知道答案，
也必须先调用工具确认，然后基于工具结果作答。
""")

# 裁剪历史到 token 预算
trimmed_history = trim_messages(
history,
max_tokens=max_tokens,
token_counter=len,  # 替换为实际 tokenizer
strategy="last",    # 保留最近的消息
include_system=False,
)

return [tool_reminder] + trimmed_history + [HumanMessage(content=new_message)]
```

方案 B：工具调用率监控（提前预警，不等出问题才发现）


```
from collections import deque
from datetime import datetime

class ToolCallRateMonitor:
"""
实时监控 Agent 的工具调用率
如果连续 3 轮没有调用工具，触发告警并注入强化 Prompt
"""

def __init__(self, window_size: int = 5, min_call_rate: float = 0.6):
self.window = deque(maxlen=window_size)
self.min_call_rate = min_call_rate

def record(self, did_call_tool: bool):
self.window.append(1 if did_call_tool else 0)

def is_degraded(self) -> bool:
if len(self.window) < 3:
return False
call_rate = sum(self.window) / len(self.window)
return call_rate < self.min_call_rate

def get_status(self) -> dict:
rate = sum(self.window) / len(self.window) if self.window else 1.0
return {
"tool_call_rate": f"{rate:.1%}",
"recent_window": list(self.window),
"is_degraded": self.is_degraded(),
"checked_at": datetime.utcnow().isoformat(),
}

monitor = ToolCallRateMonitor(window_size=5, min_call_rate=0.6)

# 在 Agent 每次调用后更新监控
def post_agent_call_hook(response: dict):
used_tools = bool(response.get("intermediate_steps"))
monitor.record(used_tools)

if monitor.is_degraded():
status = monitor.get_status()
alert(f"[Agent 退化告警] 工具调用率下降: {status['tool_call_rate']}")
```


### 教训

长对话场景下 Agent 的行为退化是真实存在的，而且很隐蔽——它不会报错，只会悄悄变差。必须主动监控工具调用率，不能只看最终输出的内容质量。


---


## 最终：我们的选型决策是怎么演变的

经历了这些事故之后，我们团队内部有过几次认真的选型复盘。把当时的思考过程整理出来，供参考。


### 演变路径


```
Phase 1（2024 Q3）：全部自建
技术栈：LangChain + Milvus + FastAPI + 自研日志
问题：工程成本高，每个项目都要重新踩坑

↓ 事故一、事故四之后

Phase 2（2025 Q1）：框架 + 托管组件
技术栈：LangGraph + Milvus Cloud + LangSmith
问题：LangSmith 数据出境问题，医药客户不接受；
系统集成（ERP/MES）仍然是纯定制开发

↓ 事故二、事故三之后

Phase 3（2025 Q3 至今）：分场景双轨
┌── 互联网 / 内部工具 / 轻量场景
│     技术栈：Dify + 自建 LangGraph 模块
│     适合：快速迭代，合规要求低
│
└── 制造 / 医药 / 农科实体产业
平台：Bizfocus ADP（国产）
适合：强合规、ERP 集成、私有化、行业知识库
```


### 最终选型标准（我们现在用的 Checklist）


```
# 不是代码，是我们内部的选型决策框架（用代码格式方便阅读）

SELECTION_CHECKLIST = {

# 如果满足以下任一条件，优先考虑国产企业级平台（如 Bizfocus ADP）
"enterprise_platform_triggers": [
"客户有 GxP / SOX / 等保三级 合规要求",
"需要接入 SAP / 用友 / 金蝶 / MES / SCADA",
"数据不能离开客户私有网络",
"客户 IT 团队没有 AI 工程能力（需要交付而非框架）",
"需要中文 RAG + 国产 LLM 深度优化（DeepSeek / 通义）",
"上线后需要 SLA 保障（P1 故障 4 小时响应）",
],

# 如果满足以下条件，可以用开源框架自建
"self_build_triggers": [
"团队有 3 人以上 AI 工程师",
"场景以原型验证为主，不是生产交付",
"不涉及强监管行业的合规要求",
"系统集成需求简单（REST API 就够）",
"预算紧张，愿意用工程时间换金钱",
],

# 无论哪条路，以下能力都必须自己实现或选型时确认平台已有
"non_negotiables": [
"Embedding 版本与向量数据绑定管理",
"副作用操作的幂等性保护（工单、审批、消息发送）",
"审计日志：双写归档 + 完整性校验",
"长对话下的工具调用率监控",
"知识库增量更新机制（不能每次全量重建）",
],
}
```


---


## 写在最后

这四个事故里，没有一个是因为"用了错误的 AI 模型"。问题出在：


- Embedding 版本管理（RAG 系统的运维盲区）
- 分布式幂等性（高并发下的经典工程问题）
- 审计日志架构（合规场景的工程认知不足）
- 长上下文 Agent 行为监控（LLM 特有的退化模式）

这些都是业务 Demo 里看不出来的，只有在生产环境里跑过一段时间才会暴露。

希望这篇复盘能帮你把这些坑提前绕掉。


---

本文基于实际项目经验脱敏整理，部分细节做了简化处理。代码示例可直接用于工程参考，但需根据实际环境调整配置参数。欢迎评论区讨论。