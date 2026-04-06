"""
长期记忆 - 跨会话持久化存储（简化版，使用数据库存储）

LTM 检索分两路：
  1. 关系型模糊检索（UserFact 表）：按关键词 LIKE 匹配历史画像/偏好，速度快，确定性强
  2. 摘要列表检索（Memory 表）：返回最近的对话摘要，补充宏观上下文
"""
from typing import List, Optional
from langchain_core.messages import BaseMessage

from database import crud


class LongTermMemory:
    def __init__(self):
        pass

    async def save_memory(
        self,
        user_id: str,
        memory_type: str,
        content: str,
        metadata: dict = None,
    ) -> str:
        mem = await crud.create_memory_record(
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            metadata=metadata or {},
        )
        return mem.id

    async def save_user_fact(
        self,
        user_id: str,
        category: str,
        key: str,
        value: str,
        source: str = "inferred",
    ) -> str:
        """将单条用户事实写入 UserFact 关系型表（支持 upsert）"""
        fact = await crud.upsert_user_fact(
            user_id=user_id,
            category=category,
            key=key,
            value=value,
            source=source,
        )
        return fact.id

    async def retrieve_relevant_memories(
        self,
        user_id: str,
        query: str = "",
        top_k: int = 5,
    ) -> List[str]:
        """
        两路检索，结果合并去重后返回字符串列表（直接注入 System Prompt）。

        路径 1：UserFact 关系型 LIKE 模糊匹配
          — 按 query 关键词命中历史画像/偏好事实，结果格式："{key}: {value}"

        路径 2：Memory 摘要表最近 N 条
          — 补充宏观对话摘要，用于长对话中的语义补全

        安全降级：任一路径失败均静默跳过，不影响主流程。
        """
        results: List[str] = []

        # ── 路径 1：关系型事实模糊检索 ───────────────────────
        if query:
            try:
                facts = await crud.search_user_facts(
                    user_id=user_id,
                    query=query,
                    top_k=top_k,
                )
                for f in facts:
                    results.append(f"[{f.category}] {f.key}: {f.value}")
            except Exception:
                pass

        # ── 路径 2：对话摘要最近条目 ─────────────────────────
        remaining = top_k - len(results)
        if remaining > 0:
            try:
                memories = await crud.get_memories_by_user(user_id)
                for m in memories[:remaining]:
                    snippet = m.content[:200] if m.content else ""
                    if snippet and snippet not in results:
                        results.append(snippet)
            except Exception:
                pass

        return results[:top_k]

    async def summarize_and_save_session(
        self,
        user_id: str,
        session_messages: List[BaseMessage],
        summary_llm=None,
    ) -> str:
        """将本轮对话压缩为摘要存入长期记忆"""
        if not session_messages:
            return ""

        if summary_llm:
            from prompt.prompt_builder import build_long_term_memory_summary_prompt
            prompt = build_long_term_memory_summary_prompt(session_messages)
            try:
                response = await summary_llm.ainvoke([prompt])
                summary = response.content
            except Exception:
                summary = f"对话包含 {len(session_messages)} 条消息"
        else:
            summary = f"对话包含 {len(session_messages)} 条消息"

        await self.save_memory(user_id, "summary", summary)
        return summary


# 全局单例
_long_term_memory = LongTermMemory()


def get_long_term_memory() -> LongTermMemory:
    return _long_term_memory
