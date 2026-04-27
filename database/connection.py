"""
数据库连接与会话管理
"""
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./everloop.db")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _ensure_skill_columns(conn):
    """轻量 SQLite 兼容迁移：补齐 skills 新增列。"""
    try:
        result = await conn.execute(text("PRAGMA table_info(skills)"))
        rows = result.fetchall()
    except Exception:
        return

    if not rows:
        return

    existing = {r[1] for r in rows}
    required = {
        "skill_type": "TEXT DEFAULT 'package'",
        "enabled": "BOOLEAN DEFAULT 1",
        "mcp_server_id": "TEXT",
        "mcp_tool_filter": "TEXT DEFAULT '[]'",
        "namespace": "TEXT",
        "schema_cache": "TEXT DEFAULT '{}'",
        "schema_synced_at": "DATETIME",
        "last_error": "TEXT",
    }

    for name, ddl in required.items():
        if name in existing:
            continue
        await conn.execute(text(f"ALTER TABLE skills ADD COLUMN {name} {ddl}"))


async def init_db():
    """初始化数据库表结构"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_skill_columns(conn)


async def get_db():
    """FastAPI Depends 函数 - 获取数据库会话"""
    async with AsyncSessionLocal() as session:
        yield session
