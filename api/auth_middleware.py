"""
JWT 鉴权中间件
"""
import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "everloop-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # 7天

# 不需要鉴权的路径
AUTH_WHITELIST = {
    "/api/auth/login",
    "/api/auth/register",
    "/health",
    "/metrics",
    "/docs",
    "/openapi.json",
}

security = HTTPBearer(auto_error=False)


def create_access_token(user_id: str, role: str = "user") -> str:
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 预检请求和白名单路径直接放行
        if request.method == "OPTIONS":
            return await call_next(request)

        if path in AUTH_WHITELIST or path.startswith("/api/auth/"):
            return await call_next(request)

        # 静态文件放行
        if path.startswith("/static") or path.startswith("/assets"):
            return await call_next(request)

        # 提取 Bearer Token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            # 对 SSE 端点更友好的提示
            return JSONResponse(
                {"detail": "未授权：请先登录获取 Token"},
                status_code=401
            )

        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return JSONResponse(
                {"detail": "Token 已过期或无效，请重新登录"},
                status_code=401
            )

        # 注入用户信息到 request.state
        request.state.user_id = payload["user_id"]
        request.state.role = payload.get("role", "user")
        request.state.is_admin = payload.get("role") == "admin"

        return await call_next(request)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None,
):
    """FastAPI Depends 函数 - 提取当前用户信息"""
    if hasattr(request, "state") and hasattr(request.state, "user_id"):
        return {
            "user_id": request.state.user_id,
            "role": request.state.role,
            "is_admin": request.state.is_admin,
        }

    if not credentials:
        raise HTTPException(status_code=401, detail="未授权")

    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    return {
        "user_id": payload["user_id"],
        "role": payload.get("role", "user"),
        "is_admin": payload.get("role") == "admin",
    }
