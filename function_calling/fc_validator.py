"""
工具调用合法性校验 - 参数类型校验、权限校验、注入检查
"""
import re
from typing import Set, Tuple, Dict, Any, List, Optional

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


def validate_tool_call_against_schema(
    *,
    tool_name: str,
    tool_args: Any,
    tools_schema: List[Dict[str, Any]],
    tools_map: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    对 LLM 生成的 function call 做机械校验。

    返回：(是否通过, 错误原因, 规范化后的参数)
    校验失败时调用方应把错误作为 tool_result 写回，而不是抛异常中断 agent loop。
    """
    try:
        if not isinstance(tool_name, str) or not tool_name.strip():
            return False, "工具名为空", {}
        tool_name = tool_name.strip()

        schema = _find_tool_schema(tool_name, tools_schema)
        if schema is None:
            return False, f"工具 '{tool_name}' 不在本轮 tools_schema 中", {}
        if tool_name not in tools_map:
            return False, f"工具 '{tool_name}' 没有可执行函数映射", {}

        if isinstance(tool_args, str):
            return False, "工具参数应为 JSON object，但收到字符串；请重新生成结构化 arguments", {}
        if tool_args is None:
            tool_args = {}
        if not isinstance(tool_args, dict):
            return False, f"工具参数应为 JSON object，但收到 {type(tool_args).__name__}", {}
        if "__parse_error" in tool_args:
            return False, f"工具参数 JSON 解析失败：{tool_args.get('__parse_error')}", {}

        parameters = schema.get("parameters") or schema.get("input_schema") or {}
        if not isinstance(parameters, dict):
            parameters = {}

        ok, reason = _validate_object(tool_args, parameters, path="arguments")
        if not ok:
            return False, reason, {}

        ok, reason = _scan_injection(tool_args)
        if not ok:
            return False, reason, {}

        return True, "", dict(tool_args)
    except Exception as exc:
        return False, f"工具调用校验器异常：{exc}", {}


def _find_tool_schema(tool_name: str, tools_schema: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for raw in tools_schema:
        if not isinstance(raw, dict):
            continue
        schema = raw.get("function") if raw.get("type") == "function" and isinstance(raw.get("function"), dict) else raw
        if schema.get("name") == tool_name:
            return schema
    return None


def _validate_object(value: Dict[str, Any], schema: Dict[str, Any], path: str) -> Tuple[bool, str]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []

    for key in required:
        if key not in value:
            return False, f"{path} 缺少必填参数 '{key}'"

    for key, arg_value in value.items():
        if key not in properties:
            if schema.get("additionalProperties") is False:
                return False, f"{path} 包含未声明参数 '{key}'"
            continue
        ok, reason = _validate_value(arg_value, properties[key], f"{path}.{key}")
        if not ok:
            return False, reason
    return True, ""


def _validate_value(value: Any, schema: Dict[str, Any], path: str) -> Tuple[bool, str]:
    if not isinstance(schema, dict):
        return True, ""

    if "enum" in schema and value not in schema.get("enum", []):
        return False, f"{path} 的值不在允许范围内：{schema.get('enum')}"

    for union_key in ("anyOf", "oneOf"):
        options = schema.get(union_key)
        if isinstance(options, list) and options:
            errors = []
            for option in options:
                ok, reason = _validate_value(value, option, path)
                if ok:
                    return True, ""
                errors.append(reason)
            return False, f"{path} 不匹配任何允许类型：{'; '.join(errors[:3])}"

    expected = schema.get("type")
    if isinstance(expected, list):
        if value is None and "null" in expected:
            return True, ""
        non_null = [t for t in expected if t != "null"]
        if not non_null:
            return True, ""
        schema = {**schema, "type": non_null[0]}
        expected = non_null[0]

    if expected is None:
        return True, ""
    if expected == "null":
        return (value is None, f"{path} 应为 null")
    if expected == "string":
        return (isinstance(value, str), f"{path} 应为 string，实际为 {type(value).__name__}")
    if expected == "boolean":
        return (isinstance(value, bool), f"{path} 应为 boolean，实际为 {type(value).__name__}")
    if expected == "integer":
        return (isinstance(value, int) and not isinstance(value, bool), f"{path} 应为 integer，实际为 {type(value).__name__}")
    if expected == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool), f"{path} 应为 number，实际为 {type(value).__name__}")
    if expected == "array":
        if not isinstance(value, list):
            return False, f"{path} 应为 array，实际为 {type(value).__name__}"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                ok, reason = _validate_value(item, item_schema, f"{path}[{idx}]")
                if not ok:
                    return False, reason
        return True, ""
    if expected == "object":
        if not isinstance(value, dict):
            return False, f"{path} 应为 object，实际为 {type(value).__name__}"
        return _validate_object(value, schema, path)
    return True, ""


def _scan_injection(arguments: Dict[str, Any]) -> Tuple[bool, str]:
    def walk(value: Any, path: str) -> Tuple[bool, str]:
        if isinstance(value, str):
            for pattern in _INJECTION_PATTERNS:
                if re.search(pattern, value, re.IGNORECASE):
                    return False, f"参数 '{path}' 包含可疑内容，已阻止"
        elif isinstance(value, dict):
            for key, child in value.items():
                ok, reason = walk(child, f"{path}.{key}" if path else key)
                if not ok:
                    return False, reason
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                ok, reason = walk(child, f"{path}[{idx}]")
                if not ok:
                    return False, reason
        return True, ""

    return walk(arguments, "")
