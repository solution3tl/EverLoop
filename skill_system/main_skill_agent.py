"""
Skill Agent 核心入口 - 懒加载设计
第一次被调用时触发完整装配流水线，之后直接使用已装配好的 react_agent 实例
"""
import asyncio
from typing import Dict, List, Optional

from langchain_core.messages import BaseMessage


class SkillAgent:
    """
    技能包 Agent。
    通过 general_agent.py 包装为 @tool 注册到主 Agent 的工具列表。
    使用双重检查锁（double-checked locking）防止并发重复初始化。
    """

    def __init__(
        self,
        skill_name: str,
        skill_package_json: Dict,
        skill_id: str = "",
    ):
        self.skill_name = skill_name
        self.skill_package_json = skill_package_json
        self.skill_id = skill_id

        # 装配阶段设置的属性
        self.virtual_fs: Dict[str, str] = {}
        self.file_cache: Dict[str, str] = {}
        self.llm = None
        self.tools: List = []
        self.system_prompt: str = ""
        self.react_agent = None

        # 双重检查锁
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def ainvoke(
        self,
        user_query: str,
        thread_id: str = "",
    ) -> str:
        """
        主入口（对外作为 @tool 注册）。
        懒加载：首次调用触发装配，之后复用实例。
        """
        # 双重检查锁
        if not self._initialized:
            async with self._init_lock:
                if not self._initialized:
                    await self._init_skill_agent()
                    self._initialized = True

        # 调用 ReAct Agent
        try:
            messages = [{"role": "user", "content": user_query}]
            from langchain_core.messages import HumanMessage
            lc_messages = [HumanMessage(content=user_query)]

            config = {"configurable": {"thread_id": thread_id or f"skill:{self.skill_id}"}}
            result = await self.react_agent.ainvoke(
                {"messages": lc_messages},
                config=config,
            )

            # 提取最终 AIMessage 内容
            result_messages = result.get("messages", [])
            if result_messages:
                last = result_messages[-1]
                content = last.content if isinstance(last.content, str) else str(last.content)
                return content
            return "（Skill Agent 无返回）"
        except Exception as e:
            return f"Skill Agent [{self.skill_name}] 执行异常：{str(e)}"

    async def _init_skill_agent(self):
        """调用装配流水线"""
        from skill_system.initializer import init_skill_agent
        await init_skill_agent(self)
