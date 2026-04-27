"""
通用异步 CRUD 封装层 - 屏蔽 SQLAlchemy Session 管理细节
"""
import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Session, Message, MCPServer, Skill, Memory, UserFact
from database.connection import AsyncSessionLocal


def _gen_id():
    return str(uuid.uuid4())


# ——— 用户 ——————————————————————————————
async def create_user(username: str, hashed_password: str, role: str = "user") -> User:
    async with AsyncSessionLocal() as db:
        user = User(id=_gen_id(), username=username, hashed_password=hashed_password, role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def get_user_by_id(user_id: str) -> Optional[User]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


async def get_user_by_username(username: str) -> Optional[User]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


# ——— 会话 ——————————————————————————————
async def create_session(user_id: str, thread_id: str = None) -> Session:
    async with AsyncSessionLocal() as db:
        if not thread_id:
            thread_id = str(uuid.uuid4())[:8]
        session = Session(id=_gen_id(), user_id=user_id, thread_id=thread_id)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session


async def get_session_by_thread_id(thread_id: str) -> Optional[Session]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Session).where(Session.thread_id == thread_id))
        return result.scalar_one_or_none()


async def update_session_last_active(thread_id: str):
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Session)
            .where(Session.thread_id == thread_id)
            .values(last_active_at=datetime.utcnow())
        )
        await db.commit()


async def end_session_db(thread_id: str):
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Session)
            .where(Session.thread_id == thread_id)
            .values(is_ended=True)
        )
        await db.commit()


# ——— 消息 ——————————————————————————————
async def add_message(
    session_id: str,
    role: str,
    content: str,
    tool_name: str = None,
    token_count: int = 0,
) -> Message:
    async with AsyncSessionLocal() as db:
        msg = Message(
            id=_gen_id(),
            session_id=session_id,
            role=role,
            content=content,
            tool_name=tool_name,
            token_count=token_count,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg


async def snip_message_content(msg_id: str, placeholder: str) -> None:
    """
    Snip / Microcompact 的数据库落地：
    将指定消息的 content 替换为占位符，标记 is_sniped = True。
    异步写回，不阻塞调用方。
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Message)
            .where(Message.id == msg_id)
            .values(content=placeholder, is_sniped=True, updated_at=datetime.utcnow())
        )
        await db.commit()


async def fold_messages(msg_ids: list[str]) -> None:
    """
    记忆折叠的数据库落地：
    将折叠区消息标记 is_folded = True，后续 SELECT 时过滤掉。
    """
    if not msg_ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Message)
            .where(Message.id.in_(msg_ids))
            .values(is_folded=True, updated_at=datetime.utcnow())
        )
        await db.commit()


async def get_messages_by_session(session_id: str, limit: int = 100) -> List[Message]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id, Message.is_folded == False)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ——— 记忆 ——————————————————————————————
async def create_memory_record(
    user_id: str,
    memory_type: str,
    content: str,
    metadata: dict = None,
) -> Memory:
    async with AsyncSessionLocal() as db:
        mem = Memory(
            id=_gen_id(),
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            metadata_=metadata or {},
        )
        db.add(mem)
        await db.commit()
        await db.refresh(mem)
        return mem


async def get_memories_by_user(user_id: str, memory_type: str = None) -> List[Memory]:
    async with AsyncSessionLocal() as db:
        query = select(Memory).where(Memory.user_id == user_id)
        if memory_type:
            query = query.where(Memory.memory_type == memory_type)
        result = await db.execute(query.order_by(Memory.created_at.desc()).limit(50))
        return list(result.scalars().all())


async def cleanup_inactive_sessions(cutoff_datetime) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(Session).where(
                Session.last_active_at < cutoff_datetime,
                Session.is_ended == False,
            )
        )
        await db.commit()
        return result.rowcount


async def delete_expired_memories() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(Memory).where(
                Memory.expires_at != None,
                Memory.expires_at < datetime.utcnow()
            )
        )
        await db.commit()
        return result.rowcount


# ——— 用户事实（UserFact）—— 关系型 LTM 检索 ————————————————

async def upsert_user_fact(
    user_id: str,
    category: str,
    key: str,
    value: str,
    source: str = "inferred",
) -> UserFact:
    """
    插入或更新用户事实（key 唯一性由 user_id + category + key 决定）。
    若已存在则更新 value / source / updated_at，否则插入新行。
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserFact).where(
                UserFact.user_id == user_id,
                UserFact.category == category,
                UserFact.key == key,
            )
        )
        fact = result.scalar_one_or_none()
        if fact:
            fact.value = value
            fact.source = source
            fact.updated_at = datetime.utcnow()
        else:
            fact = UserFact(
                id=_gen_id(),
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                source=source,
            )
            db.add(fact)
        await db.commit()
        await db.refresh(fact)
        return fact


async def search_user_facts(
    user_id: str,
    query: str,
    categories: list[str] = None,
    top_k: int = 10,
) -> list[UserFact]:
    """
    关系型 LTM 模糊检索（文本 LIKE 匹配）。

    策略：
      1. 将 query 按空格/标点切词，每个词作为独立 LIKE 条件（OR 关系）
      2. 可选按 category 过滤（如只查 preference / profile）
      3. 按 updated_at 降序返回最新的 top_k 条

    底层使用 LIKE '%keyword%'，适合 SQLite/PostgreSQL/MySQL，
    无需额外向量索引，即可实现关键词级别的画像召回。
    """
    from sqlalchemy import or_
    import re

    # 切词：按非字母数字汉字边界拆分，过滤短词
    keywords = [w for w in re.split(r"[\s，,。.!！?？、；;]+", query) if len(w) >= 2]
    if not keywords:
        keywords = [query[:20]]  # fallback：直接用 query 前20字

    async with AsyncSessionLocal() as db:
        stmt = select(UserFact).where(
            UserFact.user_id == user_id,
            UserFact.is_active == True,
        )

        if categories:
            stmt = stmt.where(UserFact.category.in_(categories))

        # 构建 OR 模糊条件：key LIKE '%kw%' OR value LIKE '%kw%'
        like_clauses = []
        for kw in keywords:
            like_clauses.append(UserFact.key.ilike(f"%{kw}%"))
            like_clauses.append(UserFact.value.ilike(f"%{kw}%"))

        if like_clauses:
            stmt = stmt.where(or_(*like_clauses))

        stmt = stmt.order_by(UserFact.updated_at.desc()).limit(top_k)
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def get_user_facts_by_category(
    user_id: str,
    category: str,
    top_k: int = 20,
) -> list[UserFact]:
    """按分类获取用户事实（不做模糊匹配，用于全量画像加载）"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserFact)
            .where(UserFact.user_id == user_id, UserFact.category == category, UserFact.is_active == True)
            .order_by(UserFact.updated_at.desc())
            .limit(top_k)
        )
        return list(result.scalars().all())


# ——— MCP Server ——————————————————————————
async def create_mcp_server(
    name: str, endpoint_url: str, owner_id: str,
    auth_type: str = "none", auth_credential: str = None,
    is_public: bool = False, description: str = ""
) -> MCPServer:
    async with AsyncSessionLocal() as db:
        server = MCPServer(
            id=_gen_id(), name=name, endpoint_url=endpoint_url,
            owner_id=owner_id, auth_type=auth_type,
            auth_credential=auth_credential, is_public=is_public,
            description=description,
        )
        db.add(server)
        await db.commit()
        await db.refresh(server)
        return server


async def get_mcp_server_by_id(server_id: str) -> Optional[MCPServer]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
        return result.scalar_one_or_none()


async def list_mcp_servers(requester_id: str, is_admin: bool = False) -> List[MCPServer]:
    async with AsyncSessionLocal() as db:
        if is_admin:
            result = await db.execute(select(MCPServer))
        else:
            from sqlalchemy import or_
            result = await db.execute(
                select(MCPServer).where(
                    or_(MCPServer.owner_id == requester_id, MCPServer.is_public == True)
                )
            )
        return list(result.scalars().all())




async def delete_mcp_server(server_id: str, requester_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
        server = result.scalar_one_or_none()
        if not server or server.owner_id != requester_id:
            return False
        await db.delete(server)
        await db.commit()
        return True

async def list_visible_skills(requester_id: str, is_admin: bool = False) -> List[Skill]:
    async with AsyncSessionLocal() as db:
        if is_admin:
            result = await db.execute(select(Skill))
        else:
            from sqlalchemy import or_
            result = await db.execute(
                select(Skill).where(
                    or_(Skill.owner_id == requester_id, Skill.is_public == True)
                )
            )
        return list(result.scalars().all())


async def get_skill_by_id(skill_id: str) -> Optional[Skill]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Skill).where(Skill.id == skill_id))
        return result.scalar_one_or_none()


async def create_skill(
    name: str,
    description: str,
    owner_id: str,
    package_json: dict = None,
    is_public: bool = False,
    version: str = "1.0.0",
    skill_type: str = "package",
    enabled: bool = True,
    mcp_server_id: str = None,
    mcp_tool_filter: list = None,
    namespace: str = None,
) -> Skill:
    async with AsyncSessionLocal() as db:
        skill = Skill(
            id=_gen_id(),
            name=name,
            description=description,
            package_json=package_json or {},
            owner_id=owner_id,
            is_public=is_public,
            version=version,
            skill_type=skill_type,
            enabled=enabled,
            mcp_server_id=mcp_server_id,
            mcp_tool_filter=mcp_tool_filter or [],
            namespace=namespace,
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        return skill


async def update_skill_enabled(skill_id: str, enabled: bool) -> Optional[Skill]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Skill).where(Skill.id == skill_id))
        skill = result.scalar_one_or_none()
        if not skill:
            return None
        skill.enabled = enabled
        await db.commit()
        await db.refresh(skill)
        return skill


async def update_skill_schema_sync(
    skill_id: str,
    schema_cache: dict,
    last_error: str = None,
) -> Optional[Skill]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Skill).where(Skill.id == skill_id))
        skill = result.scalar_one_or_none()
        if not skill:
            return None
        skill.schema_cache = schema_cache or {}
        skill.schema_synced_at = datetime.utcnow()
        skill.last_error = last_error
        await db.commit()
        await db.refresh(skill)
        return skill
