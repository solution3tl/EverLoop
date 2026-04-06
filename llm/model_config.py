"""
模型配置中心 - 从环境变量读取各模型的接入参数
"""
import os
from dataclasses import dataclass, field
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5-72b")


@dataclass
class ModelConfig:
    provider: str
    api_key: str
    base_url: str
    model_name: str
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60
    is_default: bool = False


def _load_model_registry() -> Dict[str, ModelConfig]:
    """从环境变量动态加载所有模型配置"""
    registry: Dict[str, ModelConfig] = {}

    # 先读取 .env 文件内容获取原始大小写的 key（os.environ 在 Windows 会转大写）
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    raw_model_names: Dict[str, str] = {}  # upper_key -> original_name
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("LLM_ENDPOINT__") and "=" in line:
                    raw_key = line.split("=")[0]
                    orig_name = raw_key[len("LLM_ENDPOINT__"):]
                    raw_model_names[orig_name.upper()] = orig_name

    # 扫描所有 LLM_ENDPOINT__ 开头的环境变量
    for key, value in os.environ.items():
        if key.startswith("LLM_ENDPOINT__"):
            env_model_upper = key[len("LLM_ENDPOINT__"):]
            # 优先使用 .env 里的原始大小写名，否则用 upper 版本
            model_name = raw_model_names.get(env_model_upper, env_model_upper)

            api_key_env = f"LLM_API_KEY__{env_model_upper}"
            api_key = os.getenv(api_key_env, "none")

            registry[model_name] = ModelConfig(
                provider=model_name,
                api_key=api_key,
                base_url=value,
                model_name=model_name,
                is_default=(model_name.lower() == DEFAULT_MODEL.lower()),
            )

    # 如果没有读到任何配置，添加一个本地 fallback
    if not registry:
        registry["local"] = ModelConfig(
            provider="local",
            api_key="none",
            base_url="http://localhost:11434/v1",
            model_name="llama3",
            is_default=True,
        )

    return registry


MODEL_REGISTRY: Dict[str, ModelConfig] = _load_model_registry()


def get_default_config() -> ModelConfig:
    """获取默认模型配置"""
    for config in MODEL_REGISTRY.values():
        if config.is_default:
            return config
    # fallback: 返回第一个
    return next(iter(MODEL_REGISTRY.values()))


def get_config(provider: str) -> Optional[ModelConfig]:
    """按 provider 名称精确返回配置"""
    return MODEL_REGISTRY.get(provider)


def list_models() -> list:
    """列出所有可用模型名称"""
    return list(MODEL_REGISTRY.keys())
