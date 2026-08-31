"""
命令行图执行工具
==================

作用：
    提供一个命令行入口，用于在本地测试时执行审查流水线。
    开发者可以在终端运行这个脚本来测试 LangGraph 流水线是否正常工作。

使用方式：
    python tools/run_graph.py --task demo --mode SYNC
"""

# annotations 延迟求值
from __future__ import annotations

# argparse 用于解析命令行参数
import argparse
# json 用于格式化输出
import json
# sys 用于操作 Python 路径
import sys
# Path 用于文件路径操作
from pathlib import Path
# uuid5 基于命名空间生成确定性 UUID（相同输入总是生成相同 ID）
from uuid import NAMESPACE_DNS, uuid5

# 把项目根目录加入 Python 路径，确保能导入项目模块
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 导入项目模块
from app.dependencies import get_ai_service
from schemas.enums import ReviewMode
from schemas.request import ReviewRequest

# 示例 diff 内容（用于演示）
SAMPLE_DIFF = """diff --git a/app.py b/app.py
@@ -1,3 +1,7 @@
+import logging
+
 def handler(event, context):
     return {"status": "ok"}
"""


def main():
    """命令行主函数。"""
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="Run LangGraph sample")
    parser.add_argument("--task", default="demo")  # 任务名称
    parser.add_argument("--mode", default="SYNC", choices=[mode.value for mode in ReviewMode])
    args = parser.parse_args()

    # 构建审查请求
    request = ReviewRequest(
        taskId=uuid5(NAMESPACE_DNS, args.task),  # 基于任务名生成确定性 UUID
        projectId="demo",
        repo="git@example/demo.git",
        branch="main",
        files=[{"path": "app.py", "diff": SAMPLE_DIFF}],
        mode=ReviewMode(args.mode),
    )
    # 获取 AI 服务实例并执行审查
    ai_service = get_ai_service()
    result = ai_service.run(request)
    # 格式化输出结果（indent=2 美化 JSON 输出）
    print(json.dumps(result.model_dump(by_alias=True), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
