"""
短期记忆 - 基于 thread_id 的会话内上下文窗口管理
"""
import asyncio
from typing import List, Dict, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from core.token_counter import count_tokens


class ShortTermMemory:
    def __init__(
        self,
        thread_id: str,
        max_tokens: int = 6000,
        summary_llm=None,
    ):
        self.thread_id = thread_id
        self.messages: List[BaseMessage] = []
        self.max_tokens = max_tokens
        self.summary_llm = summary_llm

    # 修复问题 #6: 删除危险的同步 add_message，统一使用 add_message_async
    # 原 add_message 在同步上下文调用 asyncio.create_task 会导致 RuntimeError
    async def add_message_async(self, message: BaseMessage):
        self.messages.append(message)
        await self._check_and_compress()

    def get_messages(self) -> List[BaseMessage]:
        return list(self.messages)

    async def _check_and_compress(self):
        """超过 token 上限时触发摘要压缩"""
        if not self.summary_llm:
            # 无压缩模型时，保留最近 20 条
            if len(self.messages) > 20:
                self.messages = self.messages[-20:]
            return

        total = count_tokens(self.messages)
        if total <= self.max_tokens:
            return

        # 压缩前半段消息
        compress_count = len(self.messages) // 2
        to_compress = self.messages[:compress_count]
        keep = self.messages[compress_count:]

        from prompt.prompt_builder import build_memory_compression_prompt
        summary_prompt = build_memory_compression_prompt(to_compress)

        try:
            response = await self.summary_llm.ainvoke([summary_prompt])
            summary_text = response.content
            compressed = SystemMessage(content=f"[历史摘要]\n{summary_text}")
            self.messages = [compressed] + keep
        except Exception:
            # 压缩失败时直接截断
            self.messages = keep

    def clear(self):
        self.messages = []


# 全局短期记忆字典：thread_id -> ShortTermMemory
_short_term_store: Dict[str, ShortTermMemory] = {}
_store_lock = asyncio.Lock()


async def get_or_create_short_term(
    thread_id: str,
    summary_llm=None,
) -> ShortTermMemory:
    if thread_id not in _short_term_store:
        _short_term_store[thread_id] = ShortTermMemory(
            thread_id=thread_id,
            summary_llm=summary_llm,
        )
    return _short_term_store[thread_id]


def get_short_term(thread_id: str) -> Optional[ShortTermMemory]:
    return _short_term_store.get(thread_id)
