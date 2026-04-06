"""
上下文隔离墙 - 确保父 Agent 只能看到子 Agent 的结果摘要
防止认知污染和无效 Token 消耗
"""
from typing import Callable, List, Optional, Any

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage


class IsolationGuard:
    """上下文隔离工具"""
    pass


def wrap_child_agent(
    child_agent_ainvoke: Callable,
    result_summarizer_llm=None,
) -> Callable:
    """
    装饰器/工厂函数：将子 Agent 的 ainvoke 包装为隔离版本。
    内部调用 child_agent.ainvoke() 得到完整输出。
    若 result_summarizer_llm 提供，压缩输出为 2-3 句摘要。
    只返回摘要，从根源切断父子间的信息过度共享。
    """
    async def isolated_ainvoke(*args, **kwargs) -> str:
        # 调用原始子 Agent
        try:
            result = await child_agent_ainvoke(*args, **kwargs)
        except Exception as e:
            return f"子 Agent 执行失败：{str(e)}"

        # 提取文本结果
        if isinstance(result, str):
            full_result = result
        elif isinstance(result, dict):
            messages = result.get("messages", [])
            if messages:
                last = messages[-1]
                full_result = last.content if isinstance(last.content, str) else str(last.content)
            else:
                full_result = str(result)
        else:
            full_result = str(result)

        # 若无摘要 LLM 或结果已足够短，直接返回
        if result_summarizer_llm is None or len(full_result) < 500:
            return full_result

        # 用摘要 LLM 压缩结果
        try:
            summary_prompt = f"""请将以下内容压缩为 2-3 句话的核心摘要，保留最关键的信息：

{full_result[:3000]}

只输出摘要，不要有其他解释。"""
            summary_response = await result_summarizer_llm.ainvoke(
                [HumanMessage(content=summary_prompt)]
            )
            return summary_response.content if isinstance(summary_response.content, str) else str(summary_response.content)
        except Exception:
            # 摘要失败则截断返回
            return full_result[:500] + "...[摘要压缩失败，已截断]"

    return isolated_ainvoke


def create_isolated_context(
    base_messages: List[BaseMessage],
    isolation_level: str = "full",
) -> List[BaseMessage]:
    """
    创建隔离的消息列表副本。
    isolation_level:
      - "full": 完全隔离，子 Agent 从空白开始（只保留 SystemMessage）
      - "partial": 只共享系统 Prompt，历史对话不共享
    """
    if isolation_level == "full":
        # 只保留 SystemMessage（人设/工具描述），不传递历史对话
        return [
            msg for msg in base_messages
            if isinstance(msg, SystemMessage)
        ]
    elif isolation_level == "partial":
        # 只保留系统消息，不共享用户/AI 历史
        return [
            msg for msg in base_messages
            if isinstance(msg, SystemMessage)
        ]
    else:
        # 默认：深拷贝整个消息列表（不共享引用）
        import copy
        return copy.deepcopy(base_messages)
