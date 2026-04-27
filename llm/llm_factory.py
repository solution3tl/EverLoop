"""
LLM 工厂 - 屏蔽不同厂商 SDK 的差异，统一返回可用的 LLM 实例。
优先使用 LangChain ChatOpenAI；缺失时降级到 OpenAI-compatible 适配器。
"""
import asyncio
import json
import urllib.request
import urllib.error
from copy import deepcopy
from typing import Any, Dict, List, Optional

from llm.model_config import get_default_config, get_config

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage

try:
    from langchain_openai import ChatOpenAI
    _HAS_LANGCHAIN_OPENAI = True
except Exception:
    ChatOpenAI = None
    _HAS_LANGCHAIN_OPENAI = False


class OpenAICompatFallbackLLM:
    """在 langchain_openai 不可用时的最小可用适配器。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._tools: List[Dict[str, Any]] = []

    def bind_tools(self, tools: List[Dict[str, Any]]):
        bound = deepcopy(self)
        bound._tools = deepcopy(tools or [])
        return bound

    async def astream(self, messages: List[BaseMessage]):
        msg = await self.ainvoke(messages)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if content:
            step = 24
            for i in range(0, len(content), step):
                yield AIMessageChunk(content=content[i:i + step])
        if msg.tool_calls:
            tc_chunks = []
            for idx, tc in enumerate(msg.tool_calls):
                tc_chunks.append(
                    {
                        "index": idx,
                        "id": tc.get("id", f"fallback_{idx}"),
                        "name": tc.get("name", ""),
                        "args": json.dumps(tc.get("args", {}), ensure_ascii=False),
                    }
                )
            yield AIMessageChunk(content="", tool_call_chunks=tc_chunks)

    async def ainvoke(self, messages: List[BaseMessage]) -> AIMessage:
        payload = {
            "model": self.model_name,
            "messages": self._to_openai_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self._tools:
            payload["tools"] = self._tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "none":
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"

        def _post_sync() -> Dict[str, Any]:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                if _looks_like_html(raw):
                    raise RuntimeError(_format_html_api_error(raw, self.model_name, url))
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"LLM API 返回非 JSON 响应：{raw[:500]}") from exc
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
                if _looks_like_html(detail):
                    detail = _format_html_api_error(detail, self.model_name, url)
                raise RuntimeError(f"HTTPError {e.code}: {detail}")
            except urllib.error.URLError as e:
                raise RuntimeError(f"URLError: {e}")

        data = await asyncio.to_thread(_post_sync)

        choice = ((data.get("choices") or [{}])[0])
        message = choice.get("message") or {}
        text = message.get("content") or ""

        tool_calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}
            tool_calls.append(
                {
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "args": args,
                    "type": "tool_call",
                }
            )

        usage = data.get("usage") or {}
        finish_reason = choice.get("finish_reason", "")

        return AIMessage(
            content=text,
            tool_calls=tool_calls,
            response_metadata={
                "token_usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                "finish_reason": finish_reason,
            },
        )

    @staticmethod
    def _to_openai_messages(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for m in messages:
            if isinstance(m, SystemMessage):
                out.append({"role": "system", "content": m.content if isinstance(m.content, str) else str(m.content)})
            elif isinstance(m, HumanMessage):
                out.append({"role": "user", "content": m.content if isinstance(m.content, str) else str(m.content)})
            elif isinstance(m, ToolMessage):
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": getattr(m, "tool_call_id", ""),
                        "content": m.content if isinstance(m.content, str) else str(m.content),
                    }
                )
            elif isinstance(m, AIMessage):
                msg = {"role": "assistant", "content": m.content if isinstance(m.content, str) else str(m.content)}
                tcs = getattr(m, "tool_calls", None) or []
                if tcs:
                    msg["tool_calls"] = [
                        {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False),
                            },
                        }
                        for tc in tcs
                    ]
                out.append(msg)
            else:
                out.append({"role": "user", "content": str(getattr(m, "content", ""))})
        return out


def _resolve_config(provider: Optional[str]):
    if provider:
        config = get_config(provider)
        if not config:
            from llm.model_config import MODEL_REGISTRY
            for k, v in MODEL_REGISTRY.items():
                if k.lower() == provider.lower():
                    config = v
                    break
        if not config:
            config = get_default_config()
    else:
        config = get_default_config()
    return config


def _looks_like_html(text: str) -> bool:
    lower = (text or "").lstrip().lower()
    return lower.startswith("<!doctype") or lower.startswith("<html") or "<html" in lower[:500]


def _format_html_api_error(html: str, model: str, url: str) -> str:
    lower = html.lower()
    if "黑名单" in html or "禁止访问" in html or "vpn" in lower or "校园网" in html or "websaas" in lower:
        return (
            f"模型 API 返回黑名单/禁止访问 HTML 页面。model={model}, url={url}。"
            "请检查是否需要 VPN/校园网，或当前 IP 是否被网关拦截。"
        )
    return f"模型 API 返回 HTML 而不是 JSON。model={model}, url={url}, preview={html[:300]}"


def create_llm(provider: str = None, overrides: dict = None) -> BaseChatModel:
    config = _resolve_config(provider)
    overrides = overrides or {}

    api_key = config.api_key if config.api_key != "none" else "sk-placeholder"
    base_url = config.base_url.replace("/chat/completions", "")
    model = config.model_name
    temperature = overrides.get("temperature", config.temperature)
    max_tokens = overrides.get("max_tokens", config.max_tokens)
    timeout = overrides.get("timeout", config.timeout)

    if _HAS_LANGCHAIN_OPENAI:
        return ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            streaming=True,
        )

    return OpenAICompatFallbackLLM(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def create_summary_llm() -> BaseChatModel:
    return create_llm(overrides={"temperature": 0.3, "max_tokens": 512})


def create_planning_llm() -> BaseChatModel:
    return create_llm(overrides={"temperature": 0.8})


def create_execution_llm() -> BaseChatModel:
    return create_llm(overrides={"temperature": 0.3})


def create_verification_llm() -> BaseChatModel:
    return create_llm(overrides={"temperature": 0.1})
