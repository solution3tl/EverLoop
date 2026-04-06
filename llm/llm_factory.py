"""
LLM 工厂 - 屏蔽不同厂商 SDK 的差异，统一返回 BaseChatModel 实例
所有模型都以 OpenAI 兼容接口接入
"""
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from llm.model_config import ModelConfig, get_default_config, get_config


def create_llm(provider: str = None, overrides: dict = None) -> BaseChatModel:
    """
    主工厂函数，按配置创建 LLM 实例
    provider: 模型名称（如 'qwen2.5-72b'），None 则用默认
    overrides: 运行时覆盖参数（temperature、max_tokens 等）
    """
    if provider:
        config = get_config(provider)
        if not config:
            # 大小写不敏感搜索
            from llm.model_config import MODEL_REGISTRY
            for k, v in MODEL_REGISTRY.items():
                if k.lower() == provider.lower():
                    config = v
                    break
        if not config:
            config = get_default_config()
    else:
        config = get_default_config()

    overrides = overrides or {}

    # 所有模型都以 OpenAI 兼容方式接入
    llm = ChatOpenAI(
        api_key=config.api_key if config.api_key != "none" else "sk-placeholder",
        base_url=config.base_url.replace("/chat/completions", ""),
        model=config.model_name,
        temperature=overrides.get("temperature", config.temperature),
        max_tokens=overrides.get("max_tokens", config.max_tokens),
        timeout=overrides.get("timeout", config.timeout),
        streaming=True,
    )
    return llm


def create_summary_llm() -> BaseChatModel:
    """轻量摘要模型（用于记忆压缩，优先用小模型节省算力）"""
    return create_llm(overrides={"temperature": 0.3, "max_tokens": 512})


def create_planning_llm() -> BaseChatModel:
    """三明治规划阶段 - 用默认最强模型，高创造性"""
    return create_llm(overrides={"temperature": 0.8})


def create_execution_llm() -> BaseChatModel:
    """三明治执行阶段 - 低温度，机械执行"""
    return create_llm(overrides={"temperature": 0.3})


def create_verification_llm() -> BaseChatModel:
    """三明治验证阶段 - 极低温度，严格校验"""
    return create_llm(overrides={"temperature": 0.1})
