"""
会话存储 - 管理 thread_id 与对话历史的持久化、TTL 清理
使用内存缓存（无 Redis 依赖）+ SQLite 持久化的二级存储策略
"""
import uuid
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import OrderedDict

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from database import crud


class SessionStore:
    """
    二级存储：
    - L1: 内存 LRU 缓存（最近 N 个活跃 session 的消息列表）
    - L2: SQLite 数据库（所有 session 的持久化存储）
    """

    def __init__(self, max_cached_sessions: int = 100):
        self._cache: OrderedDict[str, List[BaseMessage]] = OrderedDict()
        self._session_ids: Dict[str, str] = {}  # thread_id -> session.id (DB)
        self.max_cached_sessions = max_cached_sessions

    def _evict_if_needed(self):
        while len(self._cache) > self.max_cached_sessions:
            self._cache.popitem(last=False)  # LRU: 移除最旧的

    async def get_or_create_session(
        self,
        user_id: str,
        thread_id: Optional[str] = None,
    ) -> str:
        """
        获取或创建会话。
        返回 thread_id。
        """
        if thread_id:
            # 尝试从缓存恢复
            if thread_id in self._cache:
                return thread_id
            # 从数据库查找
            try:
                session = await crud.get_session_by_thread_id(thread_id)
                if session:
                    self._session_ids[thread_id] = str(session.id)
                    # 从数据库恢复消息到缓存
                    messages = await crud.get_messages_by_session(session.id, limit=50)
                    self._cache[thread_id] = [
                        self._db_msg_to_langchain(m) for m in messages
                    ]
                    self._evict_if_needed()
                    return thread_id
            except Exception:
                pass

        # 创建新 session
        if not thread_id:
            thread_id = str(uuid.uuid4())[:8]
        try:
            session = await crud.create_session(user_id=user_id, thread_id=thread_id)
            self._session_ids[thread_id] = str(session.id)
        except Exception:
            pass
        self._cache[thread_id] = []
        self._evict_if_needed()
        return thread_id

    def _db_msg_to_langchain(self, msg) -> BaseMessage:
        """将数据库消息转换为 LangChain BaseMessage"""
        role = getattr(msg, "role", "user")
        content = getattr(msg, "content", "")
        if role == "user":
            return HumanMessage(content=content)
        elif role == "assistant":
            return AIMessage(content=content)
        else:
            return SystemMessage(content=content)

    async def save_message_to_session(
        self,
        thread_id: str,
        message: BaseMessage,
    ):
        """同时写入内存缓存和数据库"""
        # L1: 内存
        if thread_id not in self._cache:
            self._cache[thread_id] = []
        self._cache[thread_id].append(message)

        # L2: 数据库
        session_id = self._session_ids.get(thread_id)
        if session_id:
            try:
                role = "user"
                if isinstance(message, AIMessage):
                    role = "assistant"
                elif isinstance(message, SystemMessage):
                    role = "system"
                content = message.content if isinstance(message.content, str) else str(message.content)
                await crud.add_message(
                    session_id=session_id,
                    role=role,
                    content=content,
                )
            except Exception:
                pass

    async def load_session_messages(
        self,
        thread_id: str,
        limit: int = 50,
    ) -> List[BaseMessage]:
        """优先从内存缓存读取，未命中则从数据库重建"""
        if thread_id in self._cache:
            messages = self._cache[thread_id]
            return messages[-limit:] if len(messages) > limit else messages

        # 从数据库重建
        session_id = self._session_ids.get(thread_id)
        if session_id:
            try:
                db_messages = await crud.get_messages_by_session(session_id, limit=limit)
                messages = [self._db_msg_to_langchain(m) for m in db_messages]
                self._cache[thread_id] = messages
                self._evict_if_needed()
                return messages
            except Exception:
                pass
        return []

    async def cleanup_inactive_sessions(self, inactivity_days: int = 7) -> int:
        """清理超过 N 天不活跃的会话（由 janitor_daemon 调用）"""
        count = 0
        try:
            cutoff = datetime.utcnow() - timedelta(days=inactivity_days)
            # 从数据库清理
            count = await crud.cleanup_inactive_sessions(cutoff)
        except Exception:
            pass
        return count

    def save_message_chunk(self, thread_id: str, chunk: str):
        """增量检查点写入（同步，用于 SSE 每次 yield 后）"""
        # 简化版：仅更新内存中最后一条 AI 消息
        if thread_id in self._cache:
            msgs = self._cache[thread_id]
            if msgs and isinstance(msgs[-1], AIMessage):
                current = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
                self._cache[thread_id][-1] = AIMessage(content=current + chunk)


# 全局单例
_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store
