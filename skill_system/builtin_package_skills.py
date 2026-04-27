"""Aggregator for built-in package skills exposed as normal Agent tools."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from langchain_core.tools import StructuredTool

from skill_system.weather_skill import build_builtin_package_skill_tools as build_weather_skill_tools
from skill_system.web_search_tavily import build_tavily_web_search_skill_tool


def build_builtin_package_skill_tools() -> Tuple[List[StructuredTool], List[Dict[str, Any]]]:
    weather_tools, weather_meta = build_weather_skill_tools()
    tavily_tool, tavily_meta = build_tavily_web_search_skill_tool()
    return [*weather_tools, tavily_tool], [*weather_meta, tavily_meta]


def list_builtin_package_skill_metadata() -> List[Dict[str, Any]]:
    _, metadata = build_builtin_package_skill_tools()
    return metadata
