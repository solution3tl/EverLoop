"""
动态 Prompt 构造器 - 模板 + 运行时数据 = 最终 Prompt
每个 LLM 调用点都有专属的 build 函数，统一从 prompt_registry 获取模板
"""
import json
from datetime import datetime
from typing import List, Dict, Optional
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage

from prompt.prompt_registry import get_template


# ─────────────────────────────────────────────
# 主 Agent
# ─────────────────────────────────────────────

def build_main_system_prompt(
    user_id: str = "",
    long_term_snippets: List[str] = None,
    available_tools: List[Dict] = None,
    extra_context: Dict = None,
) -> SystemMessage:
    """构建主 Agent 的系统提示词"""
    template = get_template("main_system")

    if long_term_snippets:
        memory_text = "\n".join(f"- {s}" for s in long_term_snippets)
    else:
        memory_text = "（暂无历史记忆）"

    if available_tools:
        tools_text = "\n".join(
            f"- **{t.get('name', '未知')}**: {t.get('description', '')}"
            for t in available_tools
        )
    else:
        tools_text = "（暂无可用工具）"

    role_description = (extra_context or {}).get("role_description", "你是一个通用智能助手")
    current_date = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    content = template.format(
        role_description=role_description,
        current_date=current_date,
        long_term_memory_snippets=memory_text,
        available_tools_summary=tools_text,
    )
    return SystemMessage(content=content)


# ─────────────────────────────────────────────
# Skill Agent
# ─────────────────────────────────────────────

def build_skill_system_prompt(skill_md_content: str) -> SystemMessage:
    """构建 Skill Agent 的系统提示词"""
    template = get_template("skill_system")
    content = template.format(skill_md_content=skill_md_content)
    return SystemMessage(content=content)


# ─────────────────────────────────────────────
# 记忆系统
# ─────────────────────────────────────────────

def build_memory_compression_prompt(messages_to_compress: List[BaseMessage]) -> HumanMessage:
    """构建短期记忆压缩指令（上下文窗口超限时触发）"""
    template = get_template("memory_compression")
    messages_text = "\n".join(
        f"[{m.__class__.__name__}]: {m.content}" for m in messages_to_compress
    )
    content = template.format(messages_to_compress=messages_text)
    return HumanMessage(content=content)


def build_long_term_memory_summary_prompt(session_messages: List[BaseMessage]) -> HumanMessage:
    """构建长期记忆固化指令（会话结束时触发）"""
    template = get_template("long_term_memory_summary")
    messages_text = "\n".join(
        f"[{m.__class__.__name__}]: {m.content}" for m in session_messages
    )
    content = template.format(session_messages=messages_text)
    return HumanMessage(content=content)


# ─────────────────────────────────────────────
# 三明治推理
# ─────────────────────────────────────────────

def build_sandwich_plan_prompt(task_description: str) -> HumanMessage:
    """构建三明治规划阶段 prompt"""
    template = get_template("sandwich_plan")
    content = template.format(task_description=task_description)
    return HumanMessage(content=content)


def build_sandwich_execute_prompt(
    task_description: str,
    execution_plan: dict,
    output_format: str,
) -> HumanMessage:
    """构建三明治执行阶段 prompt"""
    template = get_template("sandwich_execute")
    content = template.format(
        task_description=task_description,
        execution_plan=json.dumps(execution_plan, ensure_ascii=False, indent=2),
        output_format=output_format,
    )
    return HumanMessage(content=content)


def build_sandwich_execute_retry_prompt(
    task_description: str,
    execution_plan: dict,
    output_format: str,
    failure_reason: str,
) -> HumanMessage:
    """构建三明治执行阶段重试 prompt（带失败原因）"""
    template = get_template("sandwich_execute_retry")
    content = template.format(
        task_description=task_description,
        execution_plan=json.dumps(execution_plan, ensure_ascii=False, indent=2),
        output_format=output_format,
        failure_reason=failure_reason,
    )
    return HumanMessage(content=content)


def build_sandwich_verify_prompt(
    task_description: str,
    execution_plan: dict,
    execution_result: str,
) -> HumanMessage:
    """构建三明治验证阶段 prompt"""
    template = get_template("sandwich_verify")
    content = template.format(
        task_description=task_description,
        execution_plan=json.dumps(execution_plan, ensure_ascii=False, indent=2),
        execution_result=execution_result,
    )
    return HumanMessage(content=content)


def build_sandwich_verify_retry_prompt(
    task_description: str,
    execution_plan: dict,
    output_format: str,
    verify_reason: str,
    suggestions: str,
) -> HumanMessage:
    """构建三明治验证失败后的重试 prompt"""
    template = get_template("sandwich_verify_retry")
    content = template.format(
        task_description=task_description,
        execution_plan=json.dumps(execution_plan, ensure_ascii=False, indent=2),
        output_format=output_format,
        verify_reason=verify_reason,
        suggestions=suggestions,
    )
    return HumanMessage(content=content)


# ─────────────────────────────────────────────
# Swarm 多智能体
# ─────────────────────────────────────────────

def build_swarm_decompose_prompt(
    user_input: str,
    available_types: List[str],
) -> HumanMessage:
    """构建 Swarm 任务分解 prompt"""
    template = get_template("swarm_decompose")
    types_text = "、".join(available_types) if available_types else "通用（general）"
    content = template.format(
        user_input=user_input,
        available_types=types_text,
    )
    return HumanMessage(content=content)


def build_swarm_aggregate_prompt(
    user_input: str,
    results: List[str],
) -> HumanMessage:
    """构建 Swarm 结果聚合 prompt"""
    template = get_template("swarm_aggregate")
    results_text = "\n\n".join(
        f"[子任务 {i + 1}]: {r}"
        for i, r in enumerate(results)
    )
    content = template.format(
        user_input=user_input,
        results_text=results_text,
    )
    return HumanMessage(content=content)


# ─────────────────────────────────────────────
# TeamNetwork 协调者
# ─────────────────────────────────────────────

def build_team_coordinator_prompt(
    user_input: str,
    agents: Dict[str, Dict],
    mailbox_messages: List[BaseMessage],
    recent_count: int = 5,
) -> HumanMessage:
    """构建 TeamNetwork 协调者决策 prompt"""
    template = get_template("team_coordinator")
    agent_descriptions = "\n".join(
        f"- {name}: {info['description']}"
        for name, info in agents.items()
    )
    mailbox_summary = "\n".join(
        msg.content if isinstance(msg.content, str) else str(msg.content)
        for msg in mailbox_messages[-recent_count:]
    )
    content = template.format(
        user_input=user_input,
        agent_descriptions=agent_descriptions,
        mailbox_summary=mailbox_summary if mailbox_summary else "（暂无对话记录）",
    )
    return HumanMessage(content=content)
