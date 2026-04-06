"""
蜂群并发模式 (Swarm)
子 Agent 物理隔离，并行处理分配的子任务，完成后上报结果汇总
"""
import asyncio
import json
from typing import Dict, List

from langchain_core.language_models import BaseChatModel

from prompt.prompt_builder import build_swarm_decompose_prompt, build_swarm_aggregate_prompt


class SwarmRouter:
    """
    Swarm 并发模式路由器。
    子任务之间无依赖关系时，并行调度，大幅提升效率。
    """

    def __init__(self):
        self.workers: Dict[str, dict] = {}  # task_type -> {agent_ainvoke}

    def register_worker(self, task_type: str, agent_ainvoke):
        """注册 Worker Agent"""
        self.workers[task_type] = {"ainvoke": agent_ainvoke}

    async def adispatch(self, tasks: List[Dict]) -> List[str]:
        """
        并发调度所有子任务。
        返回结果列表（与 tasks 顺序对应）。
        """
        async def _run_task(task: Dict) -> str:
            task_type = task.get("task_type", "")
            subtask = task.get("subtask_description", "")
            context = task.get("context", "")

            worker = self.workers.get(task_type)
            if not worker:
                return f"[错误] 未找到处理 {task_type} 类型的 Worker"

            try:
                query = f"{subtask}\n\n上下文：{context}" if context else subtask
                result = await worker["ainvoke"](query)
                if isinstance(result, dict):
                    messages = result.get("messages", [])
                    if messages:
                        last = messages[-1]
                        return last.content if isinstance(last.content, str) else str(last.content)
                return str(result)
            except Exception as e:
                return f"[错误] Worker {task_type} 执行失败：{str(e)}"

        results = await asyncio.gather(*[_run_task(task) for task in tasks])
        return list(results)

    async def arun(self, user_input: str, decomposer_llm: BaseChatModel) -> str:
        """
        完整的 Swarm 流程：
        1. 分解任务
        2. 并发调度
        3. 聚合结果
        """
        # Step 1: 任务分解
        available_types = list(self.workers.keys())
        decompose_prompt = build_swarm_decompose_prompt(
            user_input=user_input,
            available_types=available_types,
        )

        decompose_response = await decomposer_llm.ainvoke([decompose_prompt])
        decompose_text = decompose_response.content if isinstance(decompose_response.content, str) else str(decompose_response.content)

        try:
            tasks = json.loads(decompose_text)
            if not isinstance(tasks, list):
                tasks = [{"task_type": available_types[0] if available_types else "general", "subtask_description": user_input, "context": ""}]
        except Exception:
            tasks = [{"task_type": available_types[0] if available_types else "general", "subtask_description": user_input, "context": ""}]

        # Step 2: 并发调度
        results = await self.adispatch(tasks)

        # Step 3: 聚合结果
        if len(results) == 1:
            return results[0]

        aggregate_prompt = build_swarm_aggregate_prompt(
            user_input=user_input,
            results=results,
        )

        aggregate_response = await decomposer_llm.ainvoke([aggregate_prompt])
        return aggregate_response.content if isinstance(aggregate_response.content, str) else str(aggregate_response.content)
