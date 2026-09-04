"""Kafka 异步链路模块 —— Java 生产者 → Python 消费者 → 回调回 Java。

模块结构：
  callback_producer.py  Topic 2 回调生产者（PROCESSING / RESULT / DEAD_LETTER）
  payload_client.py     回源 Java 内部端点拉取大 payload（diff/entities/relations）
  review_consumer.py    Topic 1 审查任务消费者（含 ack / 重试 / 去重 / 批提交）
"""
