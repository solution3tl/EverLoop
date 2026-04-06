"""
全局初始化入口 - 系统装配总厂
在服务启动时把所有子系统组装成主 AgentLoop
"""
import asyncio

from llm.llm_factory import create_llm, create_summary_llm
from llm.model_config import list_models
from memory.memory_manager import init_memory_manager, get_memory_manager
from core.react_agent import create_react_agent
from prompt.prompt_builder import build_main_system_prompt

# 延迟导入 builtin_tools 以触发注册副作用
import function_calling.builtin_tools  # noqa: F401

_agent_loop = None
_agent_lock = asyncio.Lock()
_memory_manager = None


async def initialize_agent(model_name: str = None):
    """
    初始化主 AgentLoop（全局单例）
    严格按照 2.0 设计文档的顺序装配
    """
    global _agent_loop, _memory_manager

    async with _agent_lock:
        if _agent_loop is not None:
            return _agent_loop

        # Step 1: 创建 LLM
        llm = create_llm(model_name)
        summary_llm = create_summary_llm()

        # Step 2: 初始化记忆系统
        _memory_manager = init_memory_manager(summary_llm=summary_llm)

        # Step 3: 获取已注册的内置工具
        from function_calling.tool_registry import get_tool_registry
        registry = get_tool_registry()
        builtin_tools = registry.get_langchain_tools()

        # Step 4: 构建系统提示词
        available_tools = [
            {"name": k, "description": v["description"]}
            for k, v in registry.get_metadata_map().items()
        ]
        system_msg = build_main_system_prompt(
            available_tools=available_tools,
            extra_context={"role_description": "你是 EverLoop，一个功能强大的 AI 助手"},
        )

        # Step 5: 创建 AgentLoop（自主行动循环，不再依赖 LangGraph MemorySaver）
        _agent_loop = create_react_agent(
            llm=llm,
            tools=builtin_tools,
            system_prompt=system_msg.content,
            memory_manager=_memory_manager,
        )

        print("[OK] General AgentLoop assembled with", len(builtin_tools), "builtin tools")
        return _agent_loop


def get_agent_executor():
    """获取已初始化的 AgentLoop（同步版本）"""
    return _agent_loop


async def get_or_init_agent(model_name: str = None):
    """获取或初始化 AgentLoop"""
    global _agent_loop
    if _agent_loop is None:
        await initialize_agent(model_name)
    return _agent_loop


def get_available_models() -> list:
    """获取所有可用模型名称"""
    return list_models()


async def reload_agent(model_name: str = None):
    """切换模型，重新初始化 AgentLoop"""
    global _agent_loop
    _agent_loop = None
    return await initialize_agent(model_name)
