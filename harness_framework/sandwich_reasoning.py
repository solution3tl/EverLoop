"""
三明治推理算力分配器
规划（强模型）→ 执行（轻模型）→ 验证（强模型）
"""
import json
from typing import Optional

from langchain_core.language_models import BaseChatModel

from prompt.prompt_builder import (
    build_sandwich_plan_prompt,
    build_sandwich_execute_prompt,
    build_sandwich_execute_retry_prompt,
    build_sandwich_verify_prompt,
    build_sandwich_verify_retry_prompt,
)


class SandwichReasoning:
    """三明治推理实例"""

    async def arun_sandwich(
        self,
        task_description: str,
        planning_llm: BaseChatModel,
        execution_llm: BaseChatModel,
        verification_llm: BaseChatModel,
        max_execution_retries: int = 3,
    ) -> str:
        """
        执行三明治推理流程。
        返回最终通过验证的执行结果。
        """
        # Step 1: 规划
        plan_prompt = build_sandwich_plan_prompt(task_description)
        plan_response = await planning_llm.ainvoke([plan_prompt])
        plan_text = plan_response.content if isinstance(plan_response.content, str) else str(plan_response.content)

        try:
            plan_json = json.loads(plan_text)
            output_format = plan_json.get("output_format", "plain_text")
        except json.JSONDecodeError:
            plan_json = {"steps": [], "output_format": "plain_text", "success_criteria": "完成任务"}
            output_format = "plain_text"

        # Step 2: 执行（带重试）
        execution_result = ""
        linter = None
        try:
            from harness_framework.deterministic_linter import DeterministicLinter
            linter = DeterministicLinter()
        except Exception:
            pass

        for attempt in range(max_execution_retries):
            if attempt == 0:
                exec_prompt = build_sandwich_execute_prompt(
                    task_description=task_description,
                    execution_plan=plan_json,
                    output_format=output_format,
                )
            else:
                exec_prompt = build_sandwich_execute_retry_prompt(
                    task_description=task_description,
                    execution_plan=plan_json,
                    output_format=output_format,
                    failure_reason=last_failure_reason,
                )

            exec_response = await execution_llm.ainvoke([exec_prompt])
            execution_result = exec_response.content if isinstance(exec_response.content, str) else str(exec_response.content)

            if linter:
                ok, reason = linter.validate_output(execution_result, output_format)
                if ok:
                    break
                last_failure_reason = reason
            else:
                break

        # Step 3: 验证
        verify_prompt = build_sandwich_verify_prompt(
            task_description=task_description,
            execution_plan=plan_json,
            execution_result=execution_result,
        )
        verify_response = await verification_llm.ainvoke([verify_prompt])
        verify_text = verify_response.content if isinstance(verify_response.content, str) else str(verify_response.content)

        try:
            verify_json = json.loads(verify_text)
            if not verify_json.get("passed", True):
                retry_prompt = build_sandwich_verify_retry_prompt(
                    task_description=task_description,
                    execution_plan=plan_json,
                    output_format=output_format,
                    verify_reason=verify_json.get("reason", ""),
                    suggestions=verify_json.get("suggestions", ""),
                )
                retry_response = await execution_llm.ainvoke([retry_prompt])
                execution_result = retry_response.content if isinstance(retry_response.content, str) else str(retry_response.content)
        except Exception:
            pass

        return execution_result
