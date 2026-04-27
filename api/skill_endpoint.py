"""
Skill 技能包管理接口
"""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from database import crud
from mcp_ecosystem import server_manager
from skill_system.runtime_mcp_skills import invalidate_runtime_skill_cache
from skill_system.builtin_package_skills import list_builtin_package_skill_metadata

router = APIRouter()


class ToggleSkillRequest(BaseModel):
    enabled: bool


class CreateMCPSkillRequest(BaseModel):
    name: str
    description: str = ""
    mcp_server_id: str
    is_public: bool = False
    namespace: Optional[str] = None
    mcp_tool_filter: list[str] = []


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    return (s.strip("_-").lower() or "skill")[:58]


def _tool_namespace(skill_name: str, namespace: Optional[str]) -> str:
    base = namespace.strip() if namespace else _slug(skill_name)
    slug = _slug(base)
    return slug if slug.startswith("skill_") else f"skill_{slug}"


async def _get_owned_or_visible_skill(skill_id: str, user_id: str, is_admin: bool):
    skill = await crud.get_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能包不存在")
    if not is_admin and skill.owner_id != user_id and not skill.is_public:
        raise HTTPException(status_code=403, detail="无权访问此技能包")
    return skill


@router.get("/list")
async def list_skills(request: Request):
    """列出当前用户可用的技能包"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)

    skills = await crud.list_visible_skills(user_id, is_admin)
    db_skills = [
            {
                "id": str(s.id),
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "is_public": s.is_public,
                "owner_id": s.owner_id,
                "skill_type": getattr(s, "skill_type", "package"),
                "enabled": getattr(s, "enabled", True),
                "mcp_server_id": getattr(s, "mcp_server_id", None),
                "namespace": getattr(s, "namespace", None),
                "schema_synced_at": s.schema_synced_at.isoformat() if getattr(s, "schema_synced_at", None) else None,
                "last_error": getattr(s, "last_error", None),
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in skills
    ]
    builtin_skills = [
        {
            "id": item["name"],
            "name": item["display_name"],
            "description": item["description"],
            "version": "builtin",
            "is_public": True,
            "owner_id": "system",
            "skill_type": item.get("skill_type", "package"),
            "enabled": True,
            "mcp_server_id": None,
            "namespace": item["name"],
            "source": item.get("source", "builtin_package_skill"),
            "homepage": item.get("homepage"),
            "read_only": item.get("read_only", True),
            "schema_synced_at": None,
            "last_error": None,
            "created_at": None,
        }
        for item in list_builtin_package_skill_metadata()
    ]
    return {"skills": [*builtin_skills, *db_skills]}


@router.post("/upload")
async def upload_skill(request: Request):
    """上传技能包（package 类型）"""
    user_id = getattr(request.state, "user_id", "anonymous")
    try:
        body = await request.json()
        name = body.get("name", "unnamed_skill")
        description = body.get("description", "")
        package_json = body.get("package_json", {})
        version = body.get("version", "1.0.0")
        is_public = bool(body.get("is_public", False))

        namespace = _tool_namespace(name, body.get("namespace"))
        existing = await crud.list_visible_skills(user_id, True)
        if any((getattr(s, "namespace", None) or _tool_namespace(s.name, None)) == namespace for s in existing):
            raise HTTPException(status_code=409, detail=f"命名空间冲突：{namespace}")

        skill = await crud.create_skill(
            name=name,
            description=description,
            owner_id=user_id,
            package_json=package_json,
            is_public=is_public,
            version=version,
            skill_type="package",
            enabled=True,
            namespace=namespace,
        )

        invalidate_runtime_skill_cache()
        return {
            "skill_id": str(skill.id),
            "name": skill.name,
            "version": skill.version,
            "namespace": skill.namespace,
            "skill_type": skill.skill_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"上传失败：{str(e)}")


@router.post("/create-mcp")
async def create_mcp_skill(req: CreateMCPSkillRequest, request: Request):
    """创建 MCP 技能包（作为主 Agent 的 skill.* 工具入口）"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)

    try:
        await server_manager.get_mcp_server(req.mcp_server_id, user_id, is_admin)
    except server_manager.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    except server_manager.PermissionDeniedError:
        raise HTTPException(status_code=403, detail="无权绑定此 MCP Server")

    namespace = _tool_namespace(req.name, req.namespace)
    existing = await crud.list_visible_skills(user_id, True)
    if any((getattr(s, "namespace", None) or _tool_namespace(s.name, None)) == namespace for s in existing):
        raise HTTPException(status_code=409, detail=f"命名空间冲突：{namespace}")

    skill = await crud.create_skill(
        name=req.name,
        description=req.description,
        owner_id=user_id,
        package_json={},
        is_public=req.is_public,
        version="1.0.0",
        skill_type="mcp",
        enabled=True,
        mcp_server_id=req.mcp_server_id,
        mcp_tool_filter=req.mcp_tool_filter,
        namespace=namespace,
    )

    invalidate_runtime_skill_cache()
    return {
        "skill_id": str(skill.id),
        "name": skill.name,
        "namespace": skill.namespace,
        "skill_type": skill.skill_type,
        "mcp_server_id": skill.mcp_server_id,
        "enabled": skill.enabled,
    }


@router.post("/{skill_id}/sync")
async def sync_skill_schema(skill_id: str, request: Request):
    """刷新 MCP skill 的远程 schema 缓存"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)

    skill = await _get_owned_or_visible_skill(skill_id, user_id, is_admin)
    if skill.skill_type != "mcp":
        raise HTTPException(status_code=400, detail="仅 mcp 类型技能支持 sync")
    if not skill.mcp_server_id:
        raise HTTPException(status_code=400, detail="技能未绑定 mcp_server_id")

    schema_cache = {}
    last_error = None
    try:
        llm_schema, ui_metadata = await server_manager.parse_server_tools_schema(
            server_id=skill.mcp_server_id,
            requester_id=user_id,
            is_admin=is_admin,
        )
        schema_cache = {"llm_schema": llm_schema, "ui_metadata": ui_metadata}
    except Exception as e:
        last_error = str(e)

    updated = await crud.update_skill_schema_sync(skill_id, schema_cache=schema_cache, last_error=last_error)
    if not updated:
        raise HTTPException(status_code=404, detail="技能包不存在")

    invalidate_runtime_skill_cache()
    return {
        "skill_id": str(updated.id),
        "synced": last_error is None,
        "schema_synced_at": updated.schema_synced_at.isoformat() if updated.schema_synced_at else None,
        "last_error": updated.last_error,
    }


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str, request: Request):
    """删除技能包"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)

    from database.models import Skill
    from database.connection import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Skill).where(Skill.id == skill_id))
        skill = result.scalar_one_or_none()
        if not skill:
            raise HTTPException(status_code=404, detail="技能包不存在")
        if not is_admin and skill.owner_id != user_id:
            raise HTTPException(status_code=403, detail="无权删除此技能包")
        await db.delete(skill)
        await db.commit()

    invalidate_runtime_skill_cache()
    return {"success": True}


@router.patch("/{skill_id}/toggle")
async def toggle_skill(skill_id: str, req: ToggleSkillRequest, request: Request):
    """启用/禁用技能包（持久化）"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)

    skill = await _get_owned_or_visible_skill(skill_id, user_id, is_admin)
    if not is_admin and skill.owner_id != user_id:
        raise HTTPException(status_code=403, detail="无权修改此技能包")

    updated = await crud.update_skill_enabled(skill_id, req.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="技能包不存在")

    invalidate_runtime_skill_cache()
    return {
        "skill_id": skill_id,
        "enabled": updated.enabled,
        "updated_at": datetime.utcnow().isoformat(),
    }


@router.get("/{skill_id}/files")
async def get_skill_files(skill_id: str, request: Request):
    """预览技能包文件树"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)

    skill = await _get_owned_or_visible_skill(skill_id, user_id, is_admin)
    return {
        "skill_id": skill_id,
        "name": skill.name,
        "files": skill.package_json or {},
    }
