"""
ORM 数据模型 - SQLAlchemy 表结构定义
使用 SQLite (aiosqlite) 作为轻量持久化方案
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, Integer,
    Float, ForeignKey, JSON, Enum
)
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON


class Base(DeclarativeBase):
    pass


def gen_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    username = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=False)
    role = Column(String(16), default="user")  # admin / user
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    sessions = relationship("Session", back_populates="user")
    memories = relationship("Memory", back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    thread_id = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)
    is_ended = Column(Boolean, default=False)

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    role = Column(String(16), nullable=False)  # user / assistant / tool
    content = Column(Text, nullable=False, default="")
    tool_name = Column(String(64), nullable=True)
    tool_call_id = Column(String(128), nullable=True)   # 保留 AIMessage↔ToolMessage 绑定键
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    token_count = Column(Integer, default=0)
    # ── 压缩状态标记 ──────────────────────────────────────────────
    # is_sniped: 该 Message 的原始内容已被 Snip/Microcompact 替换为占位符
    # is_folded: 该 Message 已被记忆折叠，后续 SELECT 时排除出 LLM 上下文
    is_sniped = Column(Boolean, default=False)
    is_folded = Column(Boolean, default=False)

    session = relationship("Session", back_populates="messages")


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    endpoint_url = Column(String(512), nullable=False)
    auth_type = Column(String(16), default="none")  # none / apikey / oauth
    auth_credential = Column(Text, nullable=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, default=datetime.utcnow)


class Skill(Base):
    __tablename__ = "skills"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    package_json = Column(JSON, default=dict)  # 虚拟文件树
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    is_public = Column(Boolean, default=False)
    version = Column(String(32), default="1.0.0")
    skill_type = Column(String(16), default="package")  # package / mcp
    enabled = Column(Boolean, default=True)
    mcp_server_id = Column(String(36), nullable=True)
    mcp_tool_filter = Column(JSON, default=list)
    namespace = Column(String(128), nullable=True)
    schema_cache = Column(JSON, default=dict)
    schema_synced_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Memory(Base):
    __tablename__ = "memories"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    memory_type = Column(String(16), default="summary")  # preference / summary / entity
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="memories")


class UserFact(Base):
    """
    用户结构化事实表 — 长期画像 / 偏好的细粒度存储。
    支持 LIKE 模糊检索，为 Step 1 的 LTM 关系型数据库检索提供数据源。

    category: 分类标签（如 "preference" / "profile" / "skill" / "context"）
    key:      事实键名（如 "language" / "timezone" / "favorite_tool"）
    value:    事实值（如 "Python" / "Asia/Shanghai" / "ripgrep"）
    source:   来源标记（如 "user_stated" / "inferred" / "session_summary"）
    """
    __tablename__ = "user_facts"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String(32), nullable=False, default="preference", index=True)
    key = Column(String(128), nullable=False)
    value = Column(Text, nullable=False)
    source = Column(String(32), default="inferred")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
