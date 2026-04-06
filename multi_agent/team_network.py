"""
多智能体协调者模式 (Coordinator)
所有子 Agent 共享一个公共上下文（Mailbox），协调者决定下一个执行的 Agent
"""
import asyncio
from typing import Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from prompt.prompt_builder import build_team_coordinator_prompt

MAX_MAILBOX_TOKENS = 6000


class TeamNetwork:
    """
    协调者模式多 Agent 网络。
    适合需要多 Agent 协同推理、互相补充信息的场景。
    """

    def __init__(self, coordinator_llm: BaseChatModel):
        self.coordinator_llm = coordinator_llm
        self.agents: Dict[str, dict] = {}  # name -> {agent_ainvoke, description}
        self.mailbox: List[BaseMessage] = []

    def register_agent(self, name: str, agent_ainvoke, description: str):
        """注册子 Agent"""
        self.agents[name] = {
            "ainvoke": agent_ainvoke,
            "description": description,
        }

    def broadcast(self, message: BaseMessage, sender: str):
        """向 mailbox 广播消息"""
        content = message.content if isinstance(message.content, str) else str(message.content)
        tagged_content = f"[{sender}]: {content}"
        self.mailbox.append(HumanMessage(content=tagged_content))

    async def _maybe_compress_mailbox(self):
        """Mailbox token 熔断检查"""
        try:
            from core.token_counter import count_tokens
            total_tokens = count_tokens(self.mailbox)
        except Exception:
            total_chars = sum(len(m.content) for m in self.mailbox if isinstance(m.content, str))
            total_tokens = total_chars // 4

        if total_tokens <= MAX_MAILBOX_TOKENS:
            return

        try:
            from harness_framework.context_optimizer import ContextOptimizer
            optimizer = ContextOptimizer()
            old_messages = self.mailbox[:-3]
            summary_text = optimizer.compress_mailbox(old_messages)
            self.mailbox = [SystemMessage(content=f"历史摘要：{summary_text}")] + self.mailbox[-3:]
        except Exception:
            self.mailbox = self.mailbox[-5:]

    async def _coordinator_decide(self, user_input: str) -> Optional[str]:
        """协调者 LLM 决定下一个 Agent"""
        decision_prompt = build_team_coordinator_prompt(
            user_input=user_input,
            agents=self.agents,
            mailbox_messages=self.mailbox,
            recent_count=5,
        )

        response = await self.coordinator_llm.ainvoke([decision_prompt])
        decision = response.content.strip() if isinstance(response.content, str) else ""

        if decision.upper() == "DONE" or decision not in self.agents:
            return None
        return decision

    async def arun_round(
        self,
        user_input: str,
        max_rounds: int = 5,
    ) -> str:
        """
        协作一轮。
        返回最终整合回答（最后一个 Agent 的输出或 coordinator 的总结）。
        """
        self.mailbox.append(HumanMessage(content=f"[User]: {user_input}"))
        last_response = ""

        for round_idx in range(max_rounds):
            await self._maybe_compress_mailbox()

            next_agent_name = await self._coordinator_decide(user_input)
            if next_agent_name is None:
                break

            agent_info = self.agents.get(next_agent_name)
            if not agent_info:
                break

            try:
                context_str = "\n".join(
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                    for msg in self.mailbox[-10:]
                )
                result = await agent_info["ainvoke"](context_str)
                if isinstance(result, dict):
                    messages = result.get("messages", [])
                    if messages:
                        last = messages[-1]
                        result = last.content if isinstance(last.content, str) else str(last.content)
                    else:
                        result = str(result)
                last_response = str(result)
            except Exception as e:
                last_response = f"Agent {next_agent_name} 执行失败：{str(e)}"

            self.broadcast(AIMessage(content=last_response), sender=next_agent_name)

        return last_response
