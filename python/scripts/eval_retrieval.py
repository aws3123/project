#!/usr/bin/env python
"""
RAG 检索质量评估脚本 —— 衡量我们的检索系统"找得准不准、排得好不好"。

什么是检索评估？
    我们的 RAG 系统需要从数据库中检索出与用户问题相关的事故/代码信息。
    但"检索效果好不好"不能凭感觉，需要用数学指标来量化。
    这个脚本就是做这件事的：用一组"标准答案"来测试检索系统。

三个核心指标：
    1. Precision@K（精确率）：
       "检索出的前 K 条结果中，有多少是真正相关的？"
       比如 K=5，检索出 5 条结果，其中 3 条相关 → P@5 = 3/5 = 0.6
       → 衡量"检索结果的纯度"

    2. Recall@K（召回率）：
       "所有真正相关的结果中，有多少被检索出来了？"
       比如总共有 4 条相关结果，检索出了 3 条 → R@5 = 3/4 = 0.75
       → 衡量"检索结果的完整性"

    3. nDCG@K（归一化折损累积增益）：
       不仅考虑"找没找到"，还考虑"排在第几位"。
       如果相关的结果排在第 1 位，比排在第 5 位得分更高。
       → 衡量"检索结果的排序质量"
       值域 [0, 1]，1 表示完美排序

使用方法：
    python -m scripts.eval_retrieval [--test-file tests/test_queries.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import math  # 数学库，提供 log2 等数学函数
import sys
from pathlib import Path

# 把项目根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import AppSettings
from services.rag_retrieval_service import RagRetrievalService

logger = logging.getLogger(__name__)


# ============================================================
# 评估指标计算函数
# ============================================================

def _dcg_at_k(relevances: list[float], k: int) -> float:
    """计算 DCG@K（Discounted Cumulative Gain，折损累积增益）。

    什么是 DCG？
        DCG 衡量的是"一组按某种顺序排列的结果的总价值"。
        关键思想：越靠前的结果，价值越大（因为用户更可能看到）。

    公式：DCG@K = Σ (2^rel_i - 1) / log2(i + 2)
        - rel_i: 第 i 个结果的相关性分数（1.0 = 相关, 0.0 = 不相关）
        - 2^rel - 1: 把相关性转成增益（相关=1, 不相关=0）
        - log2(i + 2): 位置折损因子（第1位除以1, 第2位除以1.58, 第3位除以2...）
          越靠后，增益被"折损"得越多

    参数:
        relevances: 每个检索结果的相关性分数列表（按检索顺序排列）
        k: 只看前 K 个结果

    返回:
        DCG 值（浮点数）
    """
    dcg = 0.0
    for i, rel in enumerate(relevances[:k]):
        # i 从 0 开始，所以位置折损用 log2(i + 2)
        # i=0 → log2(2)=1（第1位不折损）
        # i=1 → log2(3)≈1.58（第2位折损）
        dcg += (2 ** rel - 1) / math.log2(i + 2)
    return dcg


def _ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """计算 nDCG@K（Normalized DCG，归一化折损累积增益）。

    为什么需要"归一化"？
        原始 DCG 的值取决于有多少个相关结果，不好跨查询比较。
        nDCG = 实际 DCG / 理想 DCG（IDCG）
        理想情况：所有相关结果都排在最前面。
        nDCG=1.0 表示完美排序，0.0 表示完全没找到。

    参数:
        retrieved_ids: 检索系统返回的结果 ID 列表（按排序顺序）
        relevant_ids: 标准答案中所有相关结果的 ID 集合
        k: 只看前 K 个结果

    返回:
        nDCG 值，范围 [0.0, 1.0]
    """
    # 根据检索顺序构建相关性列表
    # 如果某个检索结果 ID 在标准答案中，标记为 1.0（相关），否则 0.0
    relevances = [1.0 if rid in relevant_ids else 0.0 for rid in retrieved_ids[:k]]
    dcg = _dcg_at_k(relevances, k)

    # 计算理想 DCG：假设所有相关结果都排在最前面
    # 比如标准答案有 3 条，那理想情况就是前 3 位都是 1.0
    ideal_relevances = [1.0] * min(len(relevant_ids), k)
    idcg = _dcg_at_k(ideal_relevances, k)

    # 避免除以零（如果标准答案为空）
    if idcg == 0:
        return 0.0
    return dcg / idcg


def _precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """计算 Precision@K（精确率）。

    公式：P@K = 前K条中相关的数量 / K

    参数:
        retrieved_ids: 检索结果 ID 列表
        relevant_ids: 标准答案 ID 集合
        k: 只看前 K 个结果
    """
    if not retrieved_ids[:k]:
        return 0.0
    # 统计前 K 个结果中有多少在标准答案集合中
    hits = sum(1 for rid in retrieved_ids[:k] if rid in relevant_ids)
    return hits / k


def _recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """计算 Recall@K（召回率）。

    公式：R@K = 前K条中相关的数量 / 标准答案中相关的总数

    参数:
        retrieved_ids: 检索结果 ID 列表
        relevant_ids: 标准答案 ID 集合
        k: 只看前 K 个结果
    """
    if not relevant_ids:
        return 0.0
    hits = sum(1 for rid in retrieved_ids[:k] if rid in relevant_ids)
    return hits / len(relevant_ids)


def _extract_id(item: dict) -> str:
    """从检索结果中提取唯一 ID。

    因为不同的数据源可能用不同的字段名作为 ID，
    所以这里按优先级尝试多个字段：
    1. "id" 字段（最直接）
    2. "title:source" 组合（事故记录）
    3. "entity_name"（代码实体）
    4. 整个字典的字符串表示（兜底）

    参数:
        item: 检索结果字典

    返回:
        字符串形式的唯一标识
    """
    return (
        item.get("id")
        or f"{item.get('title', '')}:{item.get('source', '')}"
        or item.get("entity_name", "")
        or str(item)
    )


# ============================================================
# 评估主流程
# ============================================================

def evaluate(
    test_queries: list[dict],
    service: RagRetrievalService,
    top_k: int = 5,
) -> dict:
    """对所有测试查询执行检索评估。

    流程：
        1. 遍历每个测试查询
        2. 用 RAG 检索服务获取结果
        3. 与标准答案对比，计算 P@K、R@K、nDCG@K
        4. 汇总平均值

    参数:
        test_queries: 测试查询列表，每个元素包含：
            - "query": 自然语言查询字符串
            - "code_metadata": 代码元数据列表（可选，辅助检索）
            - "relevant_ids": 标准答案（应该被检索到的结果 ID 列表）
        service: RAG 检索服务实例
        top_k: 评估时只看前 K 条结果（默认 5）

    返回:
        包含平均指标的字典：
        {"precision_at_5": 0.xx, "recall_at_5": 0.xx, "ndcg_at_5": 0.xx, "num_queries": N}
    """
    # 累加器：用于计算平均值
    total_precision = 0.0
    total_recall = 0.0
    total_ndcg = 0.0
    num_queries = len(test_queries)

    # 打印表头
    print(f"\n{'='*60}")
    print(f"Retrieval Evaluation (top_k={top_k})")
    print(f"{'='*60}")
    # {:<40} 表示左对齐、宽度40；{:>6} 表示右对齐、宽度6
    print(f"{'Query':<40} {'P@5':>6} {'R@5':>6} {'nDCG@5':>8}")
    print(f"{'-'*60}")

    for tq in test_queries:
        query = tq.get("query", "")
        code_metadata = tq.get("code_metadata")
        # 把标准答案列表转成集合（set），因为集合的查找速度是 O(1)
        relevant_ids = set(tq.get("relevant_ids", []))

        # 调用 RAG 检索服务
        # 返回：results（结果列表）、status（状态码）、reason（原因）
        results, status, reason = service.retrieve(query, code_metadata, top_k=top_k)
        # 提取每个结果的 ID
        retrieved_ids = [_extract_id(r) for r in results]

        # 计算三个指标
        p = _precision_at_k(retrieved_ids, relevant_ids, top_k)
        r = _recall_at_k(retrieved_ids, relevant_ids, top_k)
        ndcg = _ndcg_at_k(retrieved_ids, relevant_ids, top_k)

        # 累加
        total_precision += p
        total_recall += r
        total_ndcg += ndcg

        # 打印这一行的结果（查询太长就截断）
        query_label = query[:38] + ".." if len(query) > 40 else query
        print(f"{query_label:<40} {p:>6.3f} {r:>6.3f} {ndcg:>8.3f}")

    if num_queries == 0:
        print("No test queries to evaluate.")
        return {}

    # 计算平均值
    avg_p = total_precision / num_queries
    avg_r = total_recall / num_queries
    avg_ndcg = total_ndcg / num_queries

    # 打印汇总行
    print(f"{'-'*60}")
    print(f"{'AVERAGE':<40} {avg_p:>6.3f} {avg_r:>6.3f} {avg_ndcg:>8.3f}")
    print(f"{'='*60}")

    return {
        "precision_at_5": round(avg_p, 4),  # round 保留4位小数
        "recall_at_5": round(avg_r, 4),
        "ndcg_at_5": round(avg_ndcg, 4),
        "num_queries": num_queries,
    }


def load_test_queries(test_file: str) -> list[dict]:
    """从 JSON 文件加载测试查询集。

    参数:
        test_file: JSON 文件路径

    返回:
        测试查询列表。如果文件不存在或格式错误，返回空列表。

    期望的 JSON 格式：
    [
        {
            "query": "SQL注入 漏洞",
            "code_metadata": [{"name": "UserService", "language": "java"}],
            "relevant_ids": ["sql-injection:method:findByUsername:1"]
        },
        ...
    ]
    """
    path = Path(test_file)
    if not path.exists():
        logger.error("Test query file not found: %s", test_file)
        return []

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        logger.error("Test query file must be a JSON array")
        return []

    return data


def main():
    """脚本入口：解析参数，加载测试集，执行评估。"""
    parser = argparse.ArgumentParser(description="RAG retrieval quality evaluation")
    parser.add_argument(
        "--test-file",
        default="tests/test_queries.json",
        help="Path to test queries JSON file",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Top K for evaluation")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # 配置日志级别：--verbose 时用 DEBUG，否则用 INFO
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = AppSettings()
    service = RagRetrievalService(settings)
    test_queries = load_test_queries(args.test_file)

    if not test_queries:
        print(f"No test queries found in {args.test_file}")
        print("\nExample test query file format:")
        # 打印一个示例格式，方便用户创建自己的测试集
        print(json.dumps([{
            "query": "SQL注入 漏洞",
            "code_metadata": [{"name": "UserService", "language": "java"}],
            "relevant_ids": ["sql-injection:method:findByUsername:1"]
        }], indent=2, ensure_ascii=False))
        sys.exit(1)

    results = evaluate(test_queries, service, top_k=args.top_k)

    # 输出机器可读的结果（JSON 格式，方便其他脚本解析）
    print("\n--- Machine-readable results ---")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
