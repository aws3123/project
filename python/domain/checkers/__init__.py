"""静态检查器 —— 无状态确定性代码检测器。

这些检测器是独立的领域单元，但仍实现 tools.base.Tool 协议，
以便通过工具注册表（tools/registry.py）以字符串名派发调用。

依赖方向：checkers -> tools.base（SPI 在 tools、实现在 domain，不成环）。
"""
