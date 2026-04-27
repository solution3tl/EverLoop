"""
模型配置中心 - 从环境变量与 .env 读取模型接入参数
"""
import os
from dataclasses import dataclass
from typing import Dict, Optional


def _read_env_file() -> Dict[str, str]:
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    values: Dict[str, str] = {}
    if not os.path.exists(env_file):
        return values

    with open(env_file, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


ENV_FILE_VALUES = _read_env_file()
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL") or ENV_FILE_VALUES.get("DEFAULT_MODEL", "qwen2.5-72b")


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


def _get_env_value(key: str, env_file_values: Dict[str, str]) -> Optional[str]:
    # 优先读取进程环境变量，再回退 .env 文件；兼容 Windows 大写环境键
    return os.getenv(key) or os.getenv(key.upper()) or env_file_values.get(key) or env_file_values.get(key.upper())


def _load_model_registry() -> Dict[str, ModelConfig]:
    registry: Dict[str, ModelConfig] = {}

    endpoint_keys = set()
    for key in os.environ.keys():
        if key.startswith("LLM_ENDPOINT__"):
            endpoint_keys.add(key)
    for key in ENV_FILE_VALUES.keys():
        if key.startswith("LLM_ENDPOINT__"):
            endpoint_keys.add(key)

    for endpoint_key in endpoint_keys:
        model_name = endpoint_key[len("LLM_ENDPOINT__"):]
        if not model_name:
            continue

        endpoint = _get_env_value(endpoint_key, ENV_FILE_VALUES)
        if not endpoint:
            continue

        api_key = _get_env_value(f"LLM_API_KEY__{model_name}", ENV_FILE_VALUES) or "none"

        registry[model_name] = ModelConfig(
            provider=model_name,
            api_key=api_key,
            base_url=endpoint,
            model_name=model_name,
            is_default=(model_name.lower() == DEFAULT_MODEL.lower()),
        )

    if not registry:
        registry["qwen2.5-72b"] = ModelConfig(
            provider="qwen2.5-72b",
            api_key="none",
            base_url="http://localhost:11434/v1",
            model_name="qwen2.5-72b",
            is_default=True,
        )

    return registry


MODEL_REGISTRY: Dict[str, ModelConfig] = _load_model_registry()


def get_default_config() -> ModelConfig:
    for config in MODEL_REGISTRY.values():
        if config.is_default:
            return config

    for config in MODEL_REGISTRY.values():
        if config.model_name.lower() == "qwen2.5-72b":
            return config

    return next(iter(MODEL_REGISTRY.values()))


def get_config(provider: str) -> Optional[ModelConfig]:
    if not provider:
        return None

    exact = MODEL_REGISTRY.get(provider)
    if exact:
        return exact

    low = provider.lower()
    for key, cfg in MODEL_REGISTRY.items():
        if key.lower() == low:
            return cfg
    return None


def list_models() -> list:
    return list(MODEL_REGISTRY.keys())
