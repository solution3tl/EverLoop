"""
记忆调度器 - 统一门面，外层代码只需要和 MemoryManager 交互
"""
from typing import Dict, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from memory.short_term_memory import ShortTermMemory, get_or_create_short_term
from memory.long_term_memory import get_long_term_memory


class MemoryManager:
    """全局单例记忆管理器"""

    def __init__(self, summary_llm=None):
        self._summary_llm = summary_llm
        self._long_term = get_long_term_memory()

    async def add_turn(
        self,
        thread_id: str,
        user_message: HumanMessage,
        ai_message: AIMessage,
    ):
        """记录一轮对话（用户 + AI）"""
        stm = await get_or_create_short_term(thread_id, self._summary_llm)
        await stm.add_message_async(user_message)
        await stm.add_message_async(ai_message)

    async def get_context(
        self,
        thread_id: str,
        user_query: str = "",
        user_id: str = "",
    ) -> Dict:
        """获取完整上下文：短期消息列表 + 长期记忆片段"""
        stm = await get_or_create_short_term(thread_id, self._summary_llm)
        messages = stm.get_messages()

        long_term_snippets = []
        if user_id:
            try:
                long_term_snippets = await self._long_term.retrieve_relevant_memories(
                    user_id=user_id,
                    query=user_query,
                )
            except Exception:
                pass

        return {
            "messages": messages,
            "long_term_snippets": long_term_snippets,
        }

    async def end_session(self, thread_id: str, user_id: str = ""):
        """会话结束：固化长期记忆，清理短期记忆"""
        from memory.short_term_memory import _short_term_store
        stm = _short_term_store.get(thread_id)
        if stm and user_id:
            messages = stm.get_messages()
            if messages:
                await self._long_term.summarize_and_save_session(
                    user_id=user_id,
                    session_messages=messages,
                    summary_llm=self._summary_llm,
                )
            stm.clear()
            del _short_term_store[thread_id]


# 全局单例（在 general_agent.py 初始化时创建）
_memory_manager: Optional[MemoryManager] = None


def init_memory_manager(summary_llm=None) -> MemoryManager:
    global _memory_manager
    _memory_manager = MemoryManager(summary_llm=summary_llm)
    return _memory_manager


def get_memory_manager() -> Optional[MemoryManager]:
    return _memory_manager
