"""
Built-in package skill: Tavily web search.

Inspired by:
https://skills.sh/jwynia/agent-skills/web-search-tavily

The referenced skill describes a Deno script wrapper around Tavily. EverLoop
exposes the same capability as a typed StructuredTool so it participates in the
normal AgentLoop function-call flow, argument linting, and frontend trace UI.
"""

from __future__ import annotations

import json
import os
from inspect import cleandoc
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field


TavilyTopic = Literal["general", "news", "finance"]
TavilyDepth = Literal["basic", "advanced"]
TavilyTimeRange = Literal["day", "week", "month", "year", "d", "w", "m", "y"]
TavilyOutputFormat = Literal["text", "json"]


class TavilyWebSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        min_length=1,
        max_length=400,
        description="Search query. Use concise keywords; include date/version/source constraints when useful.",
    )
    topic: TavilyTopic = Field(
        "general",
        description="general=normal web search, news=recent news/current events, finance=markets/companies/financial info.",
    )
    search_depth: TavilyDepth = Field(
        "basic",
        description="basic is faster and cheaper; advanced is deeper and costs more Tavily credits.",
    )
    max_results: int = Field(
        5,
        ge=1,
        le=10,
        description="Number of results to return. Use 3-5 for normal answers, up to 10 for research.",
    )
    time_range: Optional[TavilyTimeRange] = Field(
        None,
        description="Optional recency filter: day/week/month/year or d/w/m/y.",
    )
    include_domains: List[str] = Field(
        default_factory=list,
        description="Optional list of domains to include, e.g. ['docs.python.org', 'developer.mozilla.org'].",
    )
    exclude_domains: List[str] = Field(
        default_factory=list,
        description="Optional list of domains to exclude.",
    )
    include_answer: bool = Field(
        True,
        description="Whether Tavily should include an AI-generated answer summary.",
    )
    include_raw_content: bool = Field(
        False,
        description="Whether to include cleaned raw page content. This can be slow and verbose.",
    )
    output_format: TavilyOutputFormat = Field(
        "text",
        description="text for human-readable result; json for structured raw result.",
    )


async def web_search(
    query: str,
    topic: TavilyTopic = "general",
    search_depth: TavilyDepth = "basic",
    max_results: int = 5,
    time_range: Optional[TavilyTimeRange] = None,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    include_answer: bool = True,
    include_raw_content: bool = False,
    output_format: TavilyOutputFormat = "text",
) -> str:
    """
    Search the live web using Tavily with AI-optimized results, relevance scores, optional answer summaries,
    topic filters (general/news/finance), search depth, time range, domain include/exclude filters, and JSON output.
    Use this when the user asks to search, look up current/latest information, verify facts online, or find sources.
    Do not use for weather questions when skill_weather can answer directly.
    Requires TAVILY_API_KEY in the backend environment; never returns mocked search results.
    """

    api_key = (os.getenv("TAVILY_API_KEY") or os.getenv("TAVILY_SEARCH_API_KEY") or "").strip()
    if not api_key:
        return (
            "[错误] web_search 需要配置 TAVILY_API_KEY 才能进行真实联网搜索；"
            "当前没有 API Key，因此不会返回任何编造的搜索结果或假链接。"
        )

    normalized_query = (query or "").strip()
    if not normalized_query:
        return "[错误] web_search 缺少 query。"

    payload: Dict[str, Any] = {
        "query": normalized_query,
        "topic": topic,
        "search_depth": search_depth,
        "max_results": max(1, min(int(max_results or 5), 10)),
        "include_answer": bool(include_answer),
        "include_raw_content": bool(include_raw_content),
    }

    if time_range:
        payload["time_range"] = time_range
    clean_include = _clean_domains(include_domains or [])
    clean_exclude = _clean_domains(exclude_domains or [])
    if clean_include:
        payload["include_domains"] = clean_include
    if clean_exclude:
        payload["exclude_domains"] = clean_exclude

    try:
        data = await _call_tavily(payload, api_key)
    except Exception as exc:
        return f"[错误] web_search 调用 Tavily 失败：{exc}"

    if output_format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)[:12000]

    return _format_tavily_text(data)


async def _call_tavily(payload: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code == 401:
        raise RuntimeError("Tavily API Key 无效或已过期（HTTP 401）。")
    if response.status_code == 429:
        raise RuntimeError("Tavily API 触发限流（HTTP 429），请稍后重试或降低调用频率。")
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def _format_tavily_text(data: Dict[str, Any]) -> str:
    query = data.get("query") or ""
    results = data.get("results") or []
    response_time = data.get("response_time")
    request_id = data.get("request_id")
    usage = data.get("usage") or {}

    lines = [f'Search: "{query}"', f"Found {len(results)} results" + (f" in {response_time}s" if response_time else "")]

    if data.get("answer"):
        lines.extend(["", "AI Answer:", "────────────────────────────────────────", str(data["answer"]).strip()])

    for idx, item in enumerate(results, start=1):
        title = item.get("title") or f"Result {idx}"
        url = item.get("url") or ""
        content = (item.get("content") or "").strip()
        score = item.get("score")
        published_date = item.get("published_date")
        lines.extend(["", f"{idx}. {title}", f"   {url}"])
        if content:
            lines.append(f"   {content[:700]}")
        meta = []
        if score is not None:
            meta.append(f"score={score}")
        if published_date:
            meta.append(f"published={published_date}")
        if meta:
            lines.append(f"   {' | '.join(meta)}")
        if item.get("raw_content"):
            lines.append(f"   raw_content: {str(item['raw_content'])[:1000]}")

    if usage:
        lines.extend(["", f"Usage: {usage}"])
    if request_id:
        lines.append(f"Request ID: {request_id}")

    if not results and not data.get("answer"):
        lines.append("No results returned. Try broader keywords or remove restrictive filters.")

    return "\n".join(lines)[:12000]


def _clean_domains(domains: List[str]) -> List[str]:
    result = []
    for domain in domains:
        text = str(domain or "").strip().lower()
        text = text.removeprefix("https://").removeprefix("http://").split("/")[0]
        if text and text not in result:
            result.append(text)
    return result[:50]


def build_tavily_web_search_skill_tool() -> Tuple[StructuredTool, Dict[str, Any]]:
    description = cleandoc(web_search.__doc__ or "Tavily web search")
    tool = StructuredTool.from_function(
        func=None,
        coroutine=web_search,
        name="web_search",
        description=description,
        args_schema=TavilyWebSearchArgs,
    )
    metadata = {
        "name": "web_search",
        "description": description,
        "display_name": "Web Search Tavily",
        "source": "builtin_package_skill",
        "skill_type": "package",
        "homepage": "https://skills.sh/jwynia/agent-skills/web-search-tavily",
        "read_only": True,
    }
    return tool, metadata


def list_tavily_web_search_skill_metadata() -> List[Dict[str, Any]]:
    _, metadata = build_tavily_web_search_skill_tool()
    return [metadata]
