"""
工具调用合法性校验 - 参数类型校验、权限校验、注入检查
"""
import re
from typing import Set, Tuple, Optional, Dict, Any

from function_calling.tool_registry import ToolRegistry


class ToolNotFoundError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


# 注入特征检测正则
_INJECTION_PATTERNS = [
    r'__import__', r'exec\s*\(', r'eval\s*\(', r'os\.system',
    r'subprocess', r'open\s*\(', r'<script', r'javascript:',
]


def validate_tool_call(
    tool_call: Dict[str, Any],
    user_permissions: Set[str],
    registry: ToolRegistry,
) -> Tuple[bool, str]:
    """
    校验工具调用合法性
    返回 (是否合格, 不合格原因)
    """
    name = tool_call.get("name", "")
    arguments = tool_call.get("arguments", {})

    # Step 1: 工具存在性校验
    tools_map = registry.get_tools_map()
    if name not in tools_map:
        return False, f"工具 '{name}' 不存在"

    # Step 2: 权限校验（如果 user_permissions 为空集则放行所有）
    if user_permissions and name not in user_permissions:
        return False, f"无权调用工具 '{name}'"

    # Step 3: 注入检查
    if isinstance(arguments, dict):
        for key, value in arguments.items():
            if isinstance(value, str):
                for pattern in _INJECTION_PATTERNS:
                    if re.search(pattern, value, re.IGNORECASE):
                        return False, f"参数 '{key}' 包含可疑内容，已阻止"

    return True, ""
