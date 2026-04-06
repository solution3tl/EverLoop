"""
认证接口 - 注册、登录、刷新 Token
"""
import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.auth_middleware import create_access_token
from database import crud

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(req: RegisterRequest):
    """用户注册"""
    existing = await crud.get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    user = await crud.create_user(req.username, hashed)

    return {
        "user_id": user.id,
        "username": user.username,
        "created_at": user.created_at.isoformat(),
        "message": "注册成功",
    }


@router.post("/login")
async def login(req: LoginRequest):
    """用户登录，返回 JWT"""
    user = await crud.get_user_by_username(req.username)
    if not user or not bcrypt.checkpw(req.password.encode(), user.hashed_password.encode()):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_access_token(user.id, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 604800,  # 7天秒数
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
    }


@router.get("/me")
async def get_me(user_id: str = None):
    """获取当前用户信息（需 JWT）"""
    if not user_id:
        raise HTTPException(status_code=401, detail="未授权")
    user = await crud.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at.isoformat(),
    }
