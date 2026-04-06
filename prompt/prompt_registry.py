"""
Prompt 版本注册表 - 支持多版本热切换
"""
from typing import Dict, Optional

PROMPT_REGISTRY: Dict[str, Dict[str, str]] = {}
ACTIVE_VERSIONS: Dict[str, str] = {}


def register_template(slot_name: str, version: str, template: str):
    """注册一个 Prompt 模板版本"""
    if slot_name not in PROMPT_REGISTRY:
        PROMPT_REGISTRY[slot_name] = {}
    PROMPT_REGISTRY[slot_name][version] = template
    # 第一次注册自动设为激活版本
    if slot_name not in ACTIVE_VERSIONS:
        ACTIVE_VERSIONS[slot_name] = version


def get_template(slot_name: str, version: str = None) -> str:
    """获取指定槽位的模板字符串"""
    if slot_name not in PROMPT_REGISTRY:
        raise ValueError(f"Prompt slot '{slot_name}' not registered")
    ver = version or ACTIVE_VERSIONS.get(slot_name)
    if ver not in PROMPT_REGISTRY[slot_name]:
        raise ValueError(f"Version '{ver}' not found for slot '{slot_name}'")
    return PROMPT_REGISTRY[slot_name][ver]


def set_active_version(slot_name: str, version: str) -> bool:
    """切换某槽位的激活版本（热切换，无需重启）"""
    if slot_name not in PROMPT_REGISTRY or version not in PROMPT_REGISTRY[slot_name]:
        return False
    ACTIVE_VERSIONS[slot_name] = version
    return True


# 自动注册所有默认模板
from prompt.base_templates import (
    MAIN_AGENT_SYSTEM_TEMPLATE,
    SKILL_AGENT_SYSTEM_TEMPLATE,
    MEMORY_COMPRESSION_TEMPLATE,
    LONG_TERM_MEMORY_SUMMARY_TEMPLATE,
    TOOL_RESULT_FORMAT_TEMPLATE,
    SANDWICH_PLAN_TEMPLATE,
    SANDWICH_EXECUTE_TEMPLATE,
    SANDWICH_EXECUTE_RETRY_TEMPLATE,
    SANDWICH_VERIFY_TEMPLATE,
    SANDWICH_VERIFY_RETRY_TEMPLATE,
    SWARM_DECOMPOSE_TEMPLATE,
    SWARM_AGGREGATE_TEMPLATE,
    TEAM_COORDINATOR_TEMPLATE,
)

# 主 Agent
register_template("main_system", "v1", MAIN_AGENT_SYSTEM_TEMPLATE)

# Skill Agent
register_template("skill_system", "v1", SKILL_AGENT_SYSTEM_TEMPLATE)

# 记忆系统
register_template("memory_compression", "v1", MEMORY_COMPRESSION_TEMPLATE)
register_template("long_term_memory_summary", "v1", LONG_TERM_MEMORY_SUMMARY_TEMPLATE)

# 工具结果格式化
register_template("tool_result_format", "v1", TOOL_RESULT_FORMAT_TEMPLATE)

# 三明治推理
register_template("sandwich_plan", "v1", SANDWICH_PLAN_TEMPLATE)
register_template("sandwich_execute", "v1", SANDWICH_EXECUTE_TEMPLATE)
register_template("sandwich_execute_retry", "v1", SANDWICH_EXECUTE_RETRY_TEMPLATE)
register_template("sandwich_verify", "v1", SANDWICH_VERIFY_TEMPLATE)
register_template("sandwich_verify_retry", "v1", SANDWICH_VERIFY_RETRY_TEMPLATE)

# Swarm 多智能体
register_template("swarm_decompose", "v1", SWARM_DECOMPOSE_TEMPLATE)
register_template("swarm_aggregate", "v1", SWARM_AGGREGATE_TEMPLATE)

# TeamNetwork 协调者
register_template("team_coordinator", "v1", TEAM_COORDINATOR_TEMPLATE)
