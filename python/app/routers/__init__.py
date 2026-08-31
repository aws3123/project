"""路由模块初始化 —— 导入所有路由模块，供外部引用。

__all__ 定义了模块的公开接口，表示"这个包只导出这四个路由模块"。
"""

from . import review, health, handoff, business_risk_source

__all__ = ["review", "health", "handoff", "business_risk_source"]
from . import review, health, handoff, business_risk_source

__all__ = ["review", "health", "handoff", "business_risk_source"]
