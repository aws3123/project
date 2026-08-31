"""
熔断器模块 —— Agent 的"保险丝"
==============================

本模块实现了 CircuitBreaker（熔断器），用于保护流水线免受反复失败的 Agent 拖累。

什么是熔断器？
  类比：家里的电路保险丝。当某个电器反复短路（Agent 反复失败），
  保险丝会"跳闸"（熔断），暂时切断电源（跳过该 Agent），
  等一段时间冷却后再尝试恢复（半开状态探测）。

三种状态：
  1. 关闭（Closed）→ 正常工作，允许 Agent 执行
  2. 开启（Open）  → Agent 连续失败达到阈值，暂时跳过
  3. 半开（Half-Open）→ 冷却期过后，允许一次"探测"执行，
     成功则恢复，失败则重新开启

为什么需要熔断器？
  - LLM 推理服务偶尔会超时或报错
  - 如果不熔断，每次审查都会等 45 秒超时才放弃，严重拖慢整体速度
  - 熔断后直接跳过，节省时间，等冷却后再试
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import time  # 获取当前时间戳（秒），用于计算冷却期

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    """熔断器 —— 跟踪每个 Agent 的连续失败次数，超过阈值后自动跳过。

    参数说明：
        failure_threshold: 连续失败多少次后触发熔断（默认 2 次）
        cooldown_seconds:  熔断后冷却多少秒再允许探测（默认 30 秒）

    使用方式：
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=30)
        if not breaker.is_open("security"):    # 检查是否熔断
            run_security_agent()               # 没熔断 → 执行
            breaker.record_success("security")  # 成功 → 重置计数
        else:
            breaker.record_failure("security")  # 失败 → 计数+1
    """
    failure_threshold: int = 2          # 连续失败次数阈值：达到后触发熔断
    cooldown_seconds: float = 30.0      # 冷却时间（秒）：熔断后等多久再尝试
    _failure_counts: dict[str, int] = field(default_factory=dict)    # 各 Agent 的连续失败计数
    _last_fail_time: dict[str, float] = field(default_factory=dict)  # 各 Agent 的最后失败时间

    def is_open(self, agent_name: str) -> bool:
        """检查某个 Agent 的熔断器是否处于"开启"状态（即是否应该跳过）。

        判断逻辑：
        1. 失败次数 < 阈值 → 未熔断，返回 False（允许执行）
        2. 失败次数 >= 阈值 且 距上次失败已超过冷却时间 → 半开状态，返回 False（允许探测）
        3. 失败次数 >= 阈值 且 冷却时间未到 → 熔断中，返回 True（跳过）

        类比：
          - 状态1 = 保险丝正常，电器正常工作
          - 状态2 = 保险丝冷却好了，试试能不能恢复
          - 状态3 = 保险丝还烫着，别碰
        """
        count = self._failure_counts.get(agent_name, 0)
        if count < self.failure_threshold:
            return False  # 失败次数不够，未熔断
        elapsed = time() - self._last_fail_time.get(agent_name, 0)
        if elapsed > self.cooldown_seconds:
            # 冷却期已过 → 半开状态，降低失败计数让下一次执行成为"探测"
            self._failure_counts[agent_name] = self.failure_threshold - 1
            logger.info("Circuit half-open for agent %s, allowing probe", agent_name)
            return False  # 允许探测执行
        return True  # 仍在冷却期 → 熔断中，跳过

    def record_success(self, agent_name: str) -> None:
        """记录 Agent 执行成功 —— 重置失败计数。

        类比：电器正常工作了，保险丝恢复，清零故障记录。
        """
        self._failure_counts[agent_name] = 0

    def record_failure(self, agent_name: str) -> None:
        """记录 Agent 执行失败 —— 失败计数+1，更新最后失败时间。

        如果失败次数达到阈值，触发熔断（后续调用 is_open 会返回 True）。
        类比：电器又短路了一次，记录在案，达到次数就跳闸。
        """
        prev = self._failure_counts.get(agent_name, 0)
        self._failure_counts[agent_name] = prev + 1
        self._last_fail_time[agent_name] = time()
        if prev + 1 >= self.failure_threshold:
            logger.warning("Circuit OPEN for agent %s after %d consecutive failures", agent_name, prev + 1)
