"""
FastAPI 路由总线 - 挂载所有子路由
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth_middleware import JWTAuthMiddleware
from api.auth_endpoint import router as auth_router
from api.chat_endpoint import router as chat_router
from api.mcp_endpoint import router as mcp_router
from api.skill_endpoint import router as skill_router
from database.connection import init_db
from init.general_agent import initialize_agent
from core.observability import get_metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动：初始化数据库和 Agent
    await init_db()
    await initialize_agent()
    print("[OK] EverLoop Agent initialized")

    # 启动后台守护进程
    try:
        from harness_framework.janitor_daemon import start_janitor
        janitor_tasks = await start_janitor()
        app.state.janitor_tasks = janitor_tasks
    except Exception as e:
        print(f"[WARN] Janitor daemon failed to start: {e}")

    # 启动数据库异步写回 Worker
    try:
        from core.db_write_queue import start_db_write_worker, stop_db_write_worker
        app.state.db_write_worker = await start_db_write_worker()
    except Exception as e:
        print(f"[WARN] DB write worker failed to start: {e}")

    yield

    # 关闭：清理守护进程
    if hasattr(app.state, "db_write_worker"):
        from core.db_write_queue import stop_db_write_worker
        stop_db_write_worker()
    if hasattr(app.state, "janitor_tasks"):
        for task in app.state.janitor_tasks:
            task.cancel()
    print("[BYE] EverLoop Agent shutting down...")


app = FastAPI(
    title="EverLoop Agent API",
    description="功能完整的 ReAct Agent 后端服务",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS 配置
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT 鉴权中间件
app.add_middleware(JWTAuthMiddleware)

# 挂载路由
app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
app.include_router(chat_router, prefix="/api/chat", tags=["对话"])
app.include_router(mcp_router, prefix="/api/mcp", tags=["MCP"])
app.include_router(skill_router, prefix="/api/skill", tags=["技能包"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "EverLoop Agent", "version": "2.0.0"}


@app.get("/metrics")
async def metrics():
    """Prometheus 风格指标端点（内存版）"""
    return get_metrics().dump()


@app.get("/api/chat/models")
async def models_public():
    """公开的模型列表接口（不需要鉴权）"""
    from init.general_agent import get_available_models
    from llm.model_config import get_default_config
    default = get_default_config()
    return {
        "models": get_available_models(),
        "default": default.provider if default else None,
    }
