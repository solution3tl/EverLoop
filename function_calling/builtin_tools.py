"""
内置工具集 - 搜索、时间、计算器等基础工具
模块加载时自动向全局 tool_registry 注册
"""
import ast
import operator
import datetime
import re
from typing import Optional

from function_calling.tool_registry import register_tool


@register_tool(metadata={"display_name": "获取当前时间", "icon_url": "⏰"})
async def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """获取当前时间，支持指定时区"""
    now = datetime.datetime.now()
    return now.strftime(f"%Y年%m月%d日 %H:%M:%S (本地时间)")


# 修复问题 #11: 使用 ast 安全求值替代 eval，防止代码注入
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}


def _safe_eval(node):
    """递归 AST 安全求值，只允许数字和基本运算符"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"不支持的运算符: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _SAFE_OPS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"不支持的运算符: {op_type.__name__}")
        return _SAFE_OPS[op_type](_safe_eval(node.operand))
    else:
        raise ValueError(f"不允许的表达式类型: {type(node).__name__}")


@register_tool(metadata={"display_name": "计算器", "icon_url": "🧮"})
async def calculator(expression: str) -> str:
    """安全地计算数学表达式，如：3 * (7 + 2) / 4"""
    # 安全校验：只允许数字和基本运算符
    allowed = re.match(r'^[\d\s\+\-\*\/\(\)\.\^%]+$', expression)
    if not allowed:
        return "错误：表达式包含非法字符，只允许数字和基本运算符 (+ - * / () . ^)"
    try:
        # 替换 ^ 为 **
        safe_expr = expression.replace("^", "**")
        tree = ast.parse(safe_expr, mode='eval')
        result = _safe_eval(tree.body)
        return f"计算结果：{result}"
    except Exception as e:
        return f"计算错误：{str(e)}"


@register_tool(metadata={"display_name": "网络搜索", "icon_url": "🔍"})
async def web_search(query: str, num_results: int = 3) -> str:
    """搜索互联网信息（演示模式：返回模拟结果）"""
    # 注：生产环境接入 Tavily/SerpAPI
    return f"""搜索 "{query}" 的结果（演示模式）：

1. **相关结果 1** - 这是关于 "{query}" 的示例搜索结果。
   来源：https://example.com/1

2. **相关结果 2** - 更多关于 "{query}" 的信息。
   来源：https://example.com/2

提示：当前为演示模式，如需真实搜索请配置 TAVILY_API_KEY 环境变量。"""


@register_tool(metadata={"display_name": "知识库检索", "icon_url": "📚"})
async def knowledge_base_search(query: str, top_k: int = 3) -> str:
    """在私有知识库中进行语义检索"""
    # 注：生产环境接入向量数据库
    return f'在知识库中搜索 "{query}"：\n暂无私有知识库，请上传文档后再次检索。'

