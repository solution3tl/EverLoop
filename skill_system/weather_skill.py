"""
Built-in package skill: weather.

OpenClaw's weather skill is a SKILL.md style package skill: the agent loads the
instruction and then uses a shell command such as curl against wttr.in/Open-Meteo.
In EverLoop we expose the same capability as a typed LangChain StructuredTool so:

1. the main Agent LLM can choose it by tool name + description;
2. AgentLoop can validate its function-call arguments before execution;
3. the existing frontend tool-call SSE pipeline can display the call/result.

Reference:
https://github.com/openclaw/openclaw/blob/main/skills/weather/SKILL.md
"""

from __future__ import annotations

import json
import re
from inspect import cleandoc
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field


WeatherMode = Literal["current", "rain", "forecast", "week", "json"]

WEATHER_KEYWORDS = (
    "天气",
    "气温",
    "温度",
    "降温",
    "升温",
    "下雨",
    "下雪",
    "降雨",
    "降水",
    "雨",
    "雪",
    "会冷",
    "冷吗",
    "热吗",
    "带伞",
    "穿什么",
    "出行",
)

_KNOWN_LOCATION_ALIASES = [
    "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都", "重庆", "天津", "武汉", "西安",
    "长沙", "郑州", "青岛", "济南", "厦门", "福州", "宁波", "合肥", "昆明", "贵阳", "南宁", "南昌",
    "太原", "石家庄", "沈阳", "大连", "长春", "哈尔滨", "海口", "三亚", "拉萨", "乌鲁木齐", "兰州",
    "银川", "西宁", "呼和浩特", "香港", "澳门", "台北",
    "New York", "London", "Tokyo", "Paris", "Singapore", "Seoul", "Bangkok",
]


class WeatherSkillArgs(BaseModel):
    """Arguments accepted by the built-in weather skill."""

    model_config = ConfigDict(extra="forbid")

    location: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "城市、地区或机场代码，例如 Shanghai、北京、New York、London、ORD。"
            "如果用户没有提供地点，先向用户追问，不要编造。"
        ),
    )
    mode: WeatherMode = Field(
        "current",
        description=(
            "查询类型：current=当前天气摘要；rain=是否下雨/降水概率；"
            "forecast=指定 day 的简短预报；week=未来几天较完整预报；json=原始 JSON。"
        ),
    )
    day: int = Field(
        0,
        ge=0,
        le=2,
        description="仅 mode=forecast 时使用：0=今天，1=明天，2=后天。",
    )


def detect_weather_tool_args(text: str) -> Optional[Dict[str, Any]]:
    """
    Deterministically route obvious weather questions to skill_weather.

    This is intentionally small and conservative: if it cannot find a location,
    it returns None so the Agent can ask a follow-up instead of hallucinating.
    """

    query = (text or "").strip()
    if not query:
        return None
    lowered = query.lower()
    if not any(keyword in query for keyword in WEATHER_KEYWORDS) and not any(
        word in lowered for word in ("weather", "rain", "snow", "temperature", "forecast")
    ):
        return None

    location = _extract_location_from_weather_query(query)
    if not location:
        return {"__missing_location": True}

    if any(word in query for word in ("下雨", "降雨", "降水", "带伞", "雨")) or "rain" in lowered:
        mode: WeatherMode = "rain"
    elif any(word in query for word in ("未来", "这周", "一周", "几天", "预报")) or "forecast" in lowered:
        mode = "week"
    else:
        mode = "current"

    day = 0
    if "后天" in query or "day after tomorrow" in lowered:
        day = 2
        if mode == "current":
            mode = "forecast"
    elif "明天" in query or "tomorrow" in lowered:
        day = 1
        if mode == "current":
            mode = "forecast"
    elif "今天" in query or "现在" in query or "today" in lowered or "now" in lowered:
        day = 0

    return {"location": location, "mode": mode, "day": day}


def _extract_location_from_weather_query(query: str) -> Optional[str]:
    for loc in _KNOWN_LOCATION_ALIASES:
        if loc.lower() in query.lower():
            return loc

    for keyword in ("天气", "气温", "温度", "下雨", "下雪", "降雨", "降水", "雨", "雪", "带伞", "穿什么"):
        idx = query.find(keyword)
        if idx > 0:
            loc = query[:idx].strip(" ，,。？！?：:")
            loc = re.sub(r"^(请问|我想知道|想知道|帮我看看|帮我查一下|查一下|查询|看一下)", "", loc).strip()
            loc = re.sub(r"(今天|明天|后天|现在|当前|未来|这周|一周|最近)", "", loc).strip()
            loc = re.sub(r"(会|能|要|是否|有没有|需不需要|需要)$", "", loc).strip()
            loc = re.sub(r"^(会|能|要|是否|有没有|需不需要|需要)", "", loc).strip()
            if loc and loc not in {"今天", "明天", "后天", "现在", "当前", "未来", "最近", "这周", "一周", "会", "能", "要", "下", "会下"} and len(loc) <= 40:
                return loc

    # Common Chinese pattern: 北京今天会下雨吗 / 上海明天天气怎么样
    pattern = re.compile(
        r"(?P<loc>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z\s·.-]{0,40}?)"
        r"(?:今天|明天|后天|现在|当前|未来|这周|一周|最近)?"
        r"(?:的)?"
        r"(?:天气|气温|温度|下雨|下雪|降雨|降水|雨|雪|会冷|冷吗|热吗|带伞|穿什么|出行)"
    )
    match = pattern.search(query)
    if match:
        loc = match.group("loc").strip(" ，,。？！?：:")
        loc = re.sub(r"^(请问|帮我看看|帮我查一下|查一下|查询|看一下)", "", loc).strip()
        loc = re.sub(r"(今天|明天|后天|现在|当前|未来|这周|一周|最近)$", "", loc).strip()
        loc = re.sub(r"(会|能|要|是否|有没有|需不需要|需要)$", "", loc).strip()
        loc = re.sub(r"^(会|能|要|是否|有没有|需不需要|需要)", "", loc).strip()
        if loc in {"今天", "明天", "后天", "现在", "当前", "未来", "最近", "这周", "一周", "会", "能", "要", "下", "会下"}:
            return None
        if loc and len(loc) <= 40:
            return loc

    # English-ish pattern: weather in Beijing / Beijing weather
    english = re.search(r"(?:weather|rain|temperature|forecast)\s+(?:in|for)\s+([A-Za-z][A-Za-z\s.-]{1,40})", query, re.I)
    if english:
        return english.group(1).strip()
    english = re.search(r"([A-Za-z][A-Za-z\s.-]{1,40})\s+(?:weather|rain|temperature|forecast)", query, re.I)
    if english:
        loc = english.group(1).strip()
        loc = re.sub(r"\b(today|tomorrow|tonight)\b", "", loc, flags=re.I).strip()
        return loc or None
    return None


WEATHER_CODE_ZH = {
    0: "晴",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "中阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}


async def skill_weather(location: str, mode: WeatherMode = "current", day: int = 0) -> str:
    """
    查询实时天气、温度、风、湿度、降水/是否下雨、今天/明天/后天预报或未来几天天气。
    当用户询问“天气怎么样、会不会下雨、温度多少、出行穿什么、未来几天天气”等问题时使用。
    不用于历史气候分析、官方灾害预警、航空/航海天气或高精度本地传感器数据。
    """

    normalized_location = (location or "").strip()
    if not normalized_location:
        return "[错误] 天气查询缺少 location，请提供城市、地区或机场代码。"

    try:
        return await _query_wttr(normalized_location, mode, day)
    except Exception as wttr_exc:
        # wttr.in 偶发不可用时，使用 Open-Meteo 做无 key 兜底。
        try:
            fallback = await _query_open_meteo(normalized_location, mode, day)
            return f"{fallback}\n\n（注：wttr.in 查询失败，已使用 Open-Meteo 兜底：{wttr_exc}）"
        except Exception as fallback_exc:
            return (
                "[错误] 天气查询连接失败："
                f"wttr.in={wttr_exc}; Open-Meteo fallback={fallback_exc}"
            )


async def _query_wttr(location: str, mode: WeatherMode, day: int) -> str:
    safe_location = quote(location.replace(" ", "+"), safe="+")
    url = f"https://wttr.in/{safe_location}"

    params: Dict[str, Any]
    if mode == "rain":
        params = {"format": "%l: %c %p precipitation, %h humidity", "lang": "zh-cn"}
    elif mode == "week":
        params = {"format": "v2", "lang": "zh-cn"}
    elif mode == "json":
        params = {"format": "j1", "lang": "zh-cn"}
    elif mode == "forecast":
        # wttr.in supports ?0 / ?1 / ?2 for compact forecast pages.
        url = f"{url}?{max(0, min(int(day or 0), 2))}&lang=zh-cn"
        params = {}
    else:
        params = {
            "format": "%l: %c %t (体感 %f), %w wind, %h humidity",
            "lang": "zh-cn",
        }

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        resp = await client.get(url, params=params, headers={"User-Agent": "EverLoop Weather Skill"})

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    text = resp.text.strip()
    if not text:
        raise RuntimeError("empty response")
    return text[:4000]


async def _query_open_meteo(location: str, mode: WeatherMode, day: int) -> str:
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        geo_resp = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "zh", "format": "json"},
        )
        geo_resp.raise_for_status()
        geo = geo_resp.json()

        results = geo.get("results") or []
        if not results:
            raise RuntimeError(f"Open-Meteo 找不到位置：{location}")
        place = results[0]
        lat = place["latitude"]
        lon = place["longitude"]

        forecast_resp = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code,precipitation",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
                "forecast_days": 7,
                "timezone": "auto",
            },
        )
        forecast_resp.raise_for_status()
        data = forecast_resp.json()

    display_name = ", ".join(
        part
        for part in [
            place.get("name"),
            place.get("admin1"),
            place.get("country"),
        ]
        if part
    )

    if mode == "json":
        return json.dumps({"location": display_name, "provider": "Open-Meteo", "data": data}, ensure_ascii=False)[:4000]

    current = data.get("current") or {}
    daily = data.get("daily") or {}
    idx = max(0, min(int(day or 0), 2))

    if mode in ("forecast", "rain"):
        text = _format_open_meteo_day(display_name, daily, idx)
        if mode == "rain":
            return f"{text}\n降水提示：概率越高越建议带伞；若接近 0%，通常无需担心下雨。"
        return text

    if mode == "week":
        rows = [_format_open_meteo_day(display_name, daily, i, include_location=(i == 0)) for i in range(min(7, len(daily.get("time", []))))]
        return "\n".join(rows)

    weather_code = current.get("weather_code")
    desc = WEATHER_CODE_ZH.get(weather_code, f"天气代码 {weather_code}")
    return (
        f"{display_name}: {desc}，"
        f"{current.get('temperature_2m')}°C（体感 {current.get('apparent_temperature')}°C），"
        f"湿度 {current.get('relative_humidity_2m')}%，"
        f"风速 {current.get('wind_speed_10m')} km/h，"
        f"降水 {current.get('precipitation')} mm。"
    )


def _format_open_meteo_day(display_name: str, daily: Dict[str, List[Any]], idx: int, include_location: bool = True) -> str:
    date = _daily_value(daily, "time", idx)
    code = _daily_value(daily, "weather_code", idx)
    desc = WEATHER_CODE_ZH.get(code, f"天气代码 {code}")
    t_max = _daily_value(daily, "temperature_2m_max", idx)
    t_min = _daily_value(daily, "temperature_2m_min", idx)
    pop = _daily_value(daily, "precipitation_probability_max", idx)
    rain = _daily_value(daily, "precipitation_sum", idx)
    prefix = f"{display_name} " if include_location else ""
    return f"{prefix}{date}: {desc}，{t_min}~{t_max}°C，降水概率 {pop}%，降水量 {rain} mm。"


def _daily_value(daily: Dict[str, List[Any]], key: str, idx: int) -> Optional[Any]:
    values = daily.get(key) or []
    if idx >= len(values):
        return None
    return values[idx]


def build_builtin_package_skill_tools() -> Tuple[List[StructuredTool], List[Dict[str, Any]]]:
    description = cleandoc(skill_weather.__doc__ or "Weather skill")
    tool = StructuredTool.from_function(
        func=None,
        coroutine=skill_weather,
        name="skill_weather",
        description=description,
        args_schema=WeatherSkillArgs,
    )
    metadata = {
        "name": "skill_weather",
        "description": description,
        "display_name": "Weather",
        "source": "builtin_package_skill",
        "skill_type": "package",
        "homepage": "https://github.com/openclaw/openclaw/blob/main/skills/weather/SKILL.md",
        "read_only": True,
    }
    return [tool], [metadata]


def list_builtin_package_skill_metadata() -> List[Dict[str, Any]]:
    _, metadata = build_builtin_package_skill_tools()
    return metadata
