"""
Agent 组装器 - 构建 AgentLoop 实例
LangGraph ReAct + MemorySaver 已移除，由 AgentLoop 自主控制循环与记忆
"""
from typing import List, Dict, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from core.agent_loop import AgentLoop


def create_react_agent(
    llm: BaseChatModel,
    tools: List[BaseTool],
    system_prompt: str = None,
    memory_manager=None,
) -> AgentLoop:
    """
    组装并返回 AgentLoop 实例。
    tools 为 LangChain StructuredTool 列表，内部自动提取 schema 和可调用函数。
    """
    tools_map: Dict[str, Callable] = {}
    tools_schema: List[Dict] = []

    for tool in tools:
        name = tool.name
        # 优先取 async 版本，降级到 sync
        func = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
        if func is not None:
            tools_map[name] = func

        # 提取 OpenAI function schema
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": tool.description or "",
                "parameters": tool.args_schema.model_json_schema() if tool.args_schema else {"type": "object", "properties": {}},
            },
        }
        tools_schema.append(schema)

    return AgentLoop(
        llm=llm,
        tools_map=tools_map,
        tools_schema=tools_schema,
        system_prompt=system_prompt or "",
        memory_manager=memory_manager,
    )
