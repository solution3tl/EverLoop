"""
全局初始化入口 - 系统装配总厂
在服务启动时把所有子系统组装成主 AgentLoop
"""
import asyncio

from llm.llm_factory import create_llm, create_summary_llm
from llm.model_config import list_models
from memory.memory_manager import init_memory_manager
from core.react_agent import create_react_agent
from prompt.prompt_builder import build_main_system_prompt
from skill_system.runtime_mcp_skills import build_runtime_mcp_skill_tools
from skill_system.builtin_package_skills import build_builtin_package_skill_tools

# 延迟导入 builtin_tools 以触发注册副作用
import function_calling.builtin_tools  # noqa: F401

_agent_loop = None
_agent_model_name = None
_agent_lock = asyncio.Lock()
_memory_manager = None


async def _build_base_components(model_name: str = None):
    llm = create_llm(model_name)

    global _memory_manager
    if _memory_manager is None:
        summary_llm = create_summary_llm()
        _memory_manager = init_memory_manager(summary_llm=summary_llm)

    from function_calling.tool_registry import get_tool_registry
    registry = get_tool_registry()
    builtin_tools = registry.get_langchain_tools()
    available_tools = [
        {"name": k, "description": v["description"]}
        for k, v in registry.get_metadata_map().items()
    ]
    return llm, builtin_tools, available_tools


async def create_agent_for_request(
    user_id: str,
    is_admin: bool,
    model_name: str = None,
):
    """按请求动态组装 Agent：builtin + 可见且启用的 MCP skills。"""
    llm, builtin_tools, available_tools = await _build_base_components(model_name)

    runtime_skill_tools, runtime_skill_meta = await build_runtime_mcp_skill_tools(
        user_id=user_id,
        is_admin=is_admin,
        llm=llm,
        model_name=model_name or (llm.model_name if hasattr(llm, "model_name") else ""),
    )

    package_skill_tools, package_skill_meta = build_builtin_package_skill_tools()

    merged_tools = [*builtin_tools, *runtime_skill_tools, *package_skill_tools]
    merged_tool_desc = [
        *available_tools,
        *[
            {"name": x["name"], "description": x["description"]}
            for x in runtime_skill_meta
        ],
        *[
            {"name": x["name"], "description": x["description"]}
            for x in package_skill_meta
        ],
    ]

    system_msg = build_main_system_prompt(
        available_tools=merged_tool_desc,
        extra_context={"role_description": "你是 EverLoop，一个功能强大的 AI 助手"},
    )

    return create_react_agent(
        llm=llm,
        tools=merged_tools,
        system_prompt=system_msg.content,
        memory_manager=_memory_manager,
    )


async def initialize_agent(model_name: str = None):
    """
    初始化默认主 AgentLoop（兼容旧调用路径）。
    新路径建议使用 create_agent_for_request 进行按用户动态工具组装。
    """
    global _agent_loop, _agent_model_name

    async with _agent_lock:
        if _agent_loop is not None:
            if model_name and _agent_model_name and model_name != _agent_model_name:
                _agent_loop = None
            else:
                return _agent_loop

        _agent_loop = await create_agent_for_request(
            user_id="system",
            is_admin=True,
            model_name=model_name,
        )
        _agent_model_name = model_name or (_agent_loop._model_name if hasattr(_agent_loop, "_model_name") else "default")
        print("[OK] General AgentLoop assembled (compat mode) model=", _agent_model_name)
        return _agent_loop


def get_agent_executor():
    """获取已初始化的 AgentLoop（同步版本）"""
    return _agent_loop


async def get_or_init_agent(model_name: str = None):
    """兼容旧调用方：返回默认全局 AgentLoop。"""
    global _agent_loop, _agent_model_name
    if _agent_loop is None:
        await initialize_agent(model_name)
    elif model_name and _agent_model_name and model_name != _agent_model_name:
        await reload_agent(model_name)
    return _agent_loop


def get_available_models() -> list:
    """获取所有可用模型名称"""
    return list_models()


async def reload_agent(model_name: str = None):
    """切换模型，重新初始化默认 AgentLoop"""
    global _agent_loop, _agent_model_name
    _agent_loop = None
    _agent_model_name = None
    return await initialize_agent(model_name)
