"""
运行时 MCP Skill 工具组装器
将可见且启用的 mcp skill 动态封装为主 Agent 可调用的 StructuredTool。
"""
import time
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from database import crud
from mcp_ecosystem import server_manager
from mcp_ecosystem.mcp_agent import MCPAgent


@dataclass
class _CacheItem:
    expires_at: float
    tools: List[StructuredTool]
    metadata: List[Dict]


_RUNTIME_CACHE: Dict[str, _CacheItem] = {}
_CACHE_TTL_SECONDS = 90


class SkillInvokeArgs(BaseModel):
    task: str = Field(..., description="要交给该技能执行的目标任务")


def _cache_key(user_id: str, is_admin: bool, model_name: str) -> str:
    return f"{user_id}:{int(is_admin)}:{model_name or 'default'}"


def _safe_tool_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", (value or "").strip()).strip("_-").lower()
    if not name:
        name = "skill"
    if not name.startswith("skill_"):
        name = f"skill_{name}"
    return name[:64]


def invalidate_runtime_skill_cache() -> None:
    _RUNTIME_CACHE.clear()


async def build_runtime_mcp_skill_tools(
    *,
    user_id: str,
    is_admin: bool,
    llm,
    model_name: str = "",
) -> Tuple[List[StructuredTool], List[Dict]]:
    key = _cache_key(user_id, is_admin, model_name)
    now = time.time()
    cached = _RUNTIME_CACHE.get(key)
    if cached and cached.expires_at > now:
        return cached.tools, cached.metadata

    skills = await crud.list_visible_skills(user_id, is_admin)
    tools: List[StructuredTool] = []
    metadata: List[Dict] = []

    for skill in skills:
        if getattr(skill, "skill_type", "package") != "mcp":
            continue
        if not getattr(skill, "enabled", True):
            continue
        mcp_server_id = getattr(skill, "mcp_server_id", None)
        if not mcp_server_id:
            continue

        tool_name = _safe_tool_name(getattr(skill, "namespace", None) or skill.name)
        description = skill.description or f"MCP skill: {skill.name}"
        mcp_tool_filter = getattr(skill, "mcp_tool_filter", None) or []

        async def _invoke_skill(task: str, _skill_id=str(skill.id), _mcp_server_id=str(mcp_server_id), _tool_filter=list(mcp_tool_filter)) -> str:
            # 运行时二次权限校验 + 状态校验，防止缓存越权
            skill_obj = await crud.get_skill_by_id(_skill_id)
            if not skill_obj:
                return "[错误] 技能不存在"
            if not is_admin and skill_obj.owner_id != user_id and not skill_obj.is_public:
                return "[错误] 无权调用该技能"
            if not getattr(skill_obj, "enabled", True):
                return "[错误] 技能已禁用"
            if getattr(skill_obj, "skill_type", "package") != "mcp":
                return "[错误] 该技能不是 MCP 类型"

            try:
                mcp_server = await server_manager.get_mcp_server(
                    _mcp_server_id,
                    requester_id=user_id,
                    is_admin=is_admin,
                )
            except server_manager.MCPServerNotFoundError:
                return "[错误] MCP Server 不存在"
            except server_manager.PermissionDeniedError:
                return "[错误] 无权访问 MCP Server"
            except Exception as e:
                return f"[错误] 获取 MCP Server 失败: {str(e)}"

            agent = MCPAgent(llm=llm, mcp_server=mcp_server, tool_filter=_tool_filter)
            try:
                return await agent.ainvoke(user_query=task)
            except Exception as e:
                return f"[错误] MCP 技能执行失败: {str(e)}"

        tool = StructuredTool.from_function(
            func=None,
            coroutine=_invoke_skill,
            name=tool_name,
            description=description,
            args_schema=SkillInvokeArgs,
        )
        tools.append(tool)
        metadata.append(
            {
                "name": tool_name,
                "description": description,
                "display_name": skill.name,
                "source": "mcp_skill",
                "skill_id": str(skill.id),
                "mcp_server_id": str(mcp_server_id),
            }
        )

    _RUNTIME_CACHE[key] = _CacheItem(expires_at=now + _CACHE_TTL_SECONDS, tools=tools, metadata=metadata)
    return tools, metadata
