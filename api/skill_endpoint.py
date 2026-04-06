"""
Skill 技能包管理接口
"""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class ToggleSkillRequest(BaseModel):
    enabled: bool


@router.get("/list")
async def list_skills(request: Request):
    """列出当前用户可用的技能包"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)

    try:
        from database import crud
        # 简化实现：查询 Skill 表（如果有数据的话）
        from database.models import Skill
        from database.connection import AsyncSessionLocal
        from sqlalchemy import select, or_

        async with AsyncSessionLocal() as db:
            if is_admin:
                result = await db.execute(select(Skill))
            else:
                result = await db.execute(
                    select(Skill).where(
                        or_(Skill.owner_id == user_id, Skill.is_public == True)
                    )
                )
            skills = list(result.scalars().all())

        return {
            "skills": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "description": s.description,
                    "version": s.version,
                    "is_public": s.is_public,
                    "owner_id": s.owner_id,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in skills
            ]
        }
    except Exception as e:
        return {"skills": [], "error": str(e)}


@router.post("/upload")
async def upload_skill(request: Request):
    """上传技能包（简化实现，接受 JSON 格式的技能包数据）"""
    user_id = getattr(request.state, "user_id", "anonymous")
    try:
        body = await request.json()
        name = body.get("name", "unnamed_skill")
        description = body.get("description", "")
        package_json = body.get("package_json", {})
        version = body.get("version", "1.0.0")

        from database.models import Skill
        from database.connection import AsyncSessionLocal
        import uuid

        async with AsyncSessionLocal() as db:
            skill = Skill(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                package_json=package_json,
                owner_id=user_id,
                is_public=False,
                version=version,
            )
            db.add(skill)
            await db.commit()
            await db.refresh(skill)

        return {"skill_id": str(skill.id), "name": skill.name, "version": skill.version}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"上传失败：{str(e)}")


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str, request: Request):
    """删除技能包"""
    user_id = getattr(request.state, "user_id", "anonymous")
    is_admin = getattr(request.state, "is_admin", False)

    try:
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

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{skill_id}/toggle")
async def toggle_skill(skill_id: str, req: ToggleSkillRequest, request: Request):
    """启用/禁用技能包"""
    return {"skill_id": skill_id, "enabled": req.enabled}


@router.get("/{skill_id}/files")
async def get_skill_files(skill_id: str, request: Request):
    """预览技能包文件树"""
    try:
        from database.models import Skill
        from database.connection import AsyncSessionLocal
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Skill).where(Skill.id == skill_id))
            skill = result.scalar_one_or_none()
            if not skill:
                raise HTTPException(status_code=404, detail="技能包不存在")

        return {
            "skill_id": skill_id,
            "name": skill.name,
            "files": skill.package_json or {},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
