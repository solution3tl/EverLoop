"""
Token 计量模块 - 供记忆压缩、上下文优化使用
"""
from typing import List
from langchain_core.messages import BaseMessage

try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False

_token_cache = {}


def count_tokens(messages: List[BaseMessage], model: str = "gpt-4o") -> int:
    """精确计算消息列表的 token 数"""
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += count_str_tokens(content, model)
    return total


def count_str_tokens(text: str, model: str = "gpt-4o") -> int:
    """计算单个字符串的 token 数"""
    if not text:
        return 0

    cache_key = (text[:100], model)
    if cache_key in _token_cache:
        return _token_cache[cache_key]

    if _TIKTOKEN_AVAILABLE:
        try:
            enc = tiktoken.encoding_for_model("gpt-4o")
            count = len(enc.encode(text))
        except Exception:
            count = len(text) // 3  # fallback: 粗略估算
    else:
        # 粗略估算：中文约1.5字/token，英文约4字符/token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        count = int(chinese_chars / 1.5 + other_chars / 4)

    _token_cache[cache_key] = count
    return count
