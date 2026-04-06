"""
工具注册表 - 所有工具的中央登记处
"""
from typing import Dict, List, Callable, Optional, Any
import inspect
import json


class ToolRegistry:
    def __init__(self):
        self._tools_map: Dict[str, Callable] = {}
        self._tools_schema: List[Dict] = []
        self._metadata_map: Dict[str, Dict] = {}

    def register(self, func: Callable, metadata: dict = None):
        """注册一个工具函数"""
        name = func.__name__
        description = inspect.getdoc(func) or f"工具：{name}"
        # 生成简单的 schema
        sig = inspect.signature(func)
        properties = {}
        required = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "kwargs"):
                continue
            param_type = "string"
            annotation = param.annotation
            if annotation == int:
                param_type = "integer"
            elif annotation == float:
                param_type = "number"
            elif annotation == bool:
                param_type = "boolean"

            properties[param_name] = {
                "type": param_type,
                "description": f"参数：{param_name}",
            }
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
        self._tools_map[name] = func
        self._tools_schema.append(schema)
        self._metadata_map[name] = {
            "display_name": metadata.get("display_name", name) if metadata else name,
            "description": description,
            "icon_url": metadata.get("icon_url", "") if metadata else "",
        }

    def get_tools_schema(self, filter_names: List[str] = None) -> List[Dict]:
        if filter_names:
            return [s for s in self._tools_schema if s["function"]["name"] in filter_names]
        return list(self._tools_schema)

    def get_tools_map(self, filter_names: List[str] = None) -> Dict[str, Callable]:
        if filter_names:
            return {k: v for k, v in self._tools_map.items() if k in filter_names}
        return dict(self._tools_map)

    def get_metadata_map(self) -> Dict[str, Dict]:
        return dict(self._metadata_map)

    def get_langchain_tools(self):
        """返回 LangChain 格式的工具列表"""
        from langchain_core.tools import StructuredTool
        tools = []
        for name, func in self._tools_map.items():
            # 修复问题 #14: async 工具应只设置 coroutine，func 传 None
            # 否则 LangGraph 在某些版本会优先调用同步 func，在 async 事件循环里阻塞
            is_async = inspect.iscoroutinefunction(func)
            tool = StructuredTool.from_function(
                func=None if is_async else func,
                coroutine=func if is_async else None,
                name=name,
                description=inspect.getdoc(func) or name,
            )
            tools.append(tool)
        return tools


# 全局注册表单例
_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _tool_registry


def register_tool(metadata: dict = None):
    """装饰器：自动注册工具到全局注册表"""
    def decorator(func: Callable):
        _tool_registry.register(func, metadata)
        return func
    return decorator
