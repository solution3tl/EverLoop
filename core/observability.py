"""
可观测性模块 - 内存版 Metrics（不依赖 Prometheus/OpenTelemetry 安装）
记录 LLM 调用、工具调用等关键指标，暴露 /metrics 端点
"""
import time
from collections import defaultdict
from typing import Dict, List
from dataclasses import dataclass, field


@dataclass
class MetricPoint:
    value: float
    timestamp: float
    labels: Dict[str, str]


class Counter:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._counts: Dict[str, float] = defaultdict(float)

    def inc(self, labels: Dict[str, str] = None, amount: float = 1.0):
        key = str(sorted((labels or {}).items()))
        self._counts[key] += amount

    def collect(self) -> List[Dict]:
        return [
            {"name": self.name, "labels": dict(eval(k)), "value": v}
            for k, v in self._counts.items()
        ]


class Histogram:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._samples: List[MetricPoint] = []

    def observe(self, value: float, labels: Dict[str, str] = None):
        self._samples.append(MetricPoint(
            value=value,
            timestamp=time.time(),
            labels=labels or {},
        ))
        # 保留最近 1000 条样本，避免内存无限增长
        if len(self._samples) > 1000:
            self._samples = self._samples[-1000:]

    def collect(self) -> List[Dict]:
        return [
            {
                "name": self.name,
                "labels": s.labels,
                "value": s.value,
                "timestamp": s.timestamp,
            }
            for s in self._samples
        ]


class MetricsRegistry:
    def __init__(self):
        # LLM 相关
        self.llm_calls_total = Counter(
            "llm_calls_total", "LLM 调用总次数"
        )
        self.llm_response_time = Histogram(
            "llm_response_time_seconds", "LLM 响应时间（秒）"
        )

        # 工具相关
        self.tool_calls_total = Counter(
            "tool_calls_total", "工具调用总次数"
        )
        self.tool_call_duration = Histogram(
            "tool_call_duration_ms", "工具调用耗时（毫秒）"
        )

        # MCP 相关
        self.mcp_server_errors = Counter(
            "mcp_server_errors_total", "MCP Server 错误次数"
        )

        # 请求相关
        self.chat_requests_total = Counter(
            "chat_requests_total", "对话请求总次数"
        )

    def record_llm_call(self, provider: str, model: str, status: str, duration_seconds: float):
        labels = {"provider": provider, "model": model, "status": status}
        self.llm_calls_total.inc(labels)
        self.llm_response_time.observe(duration_seconds, labels)

    def record_tool_call(self, tool_name: str, status: str, duration_ms: float):
        labels = {"tool_name": tool_name, "status": status}
        self.tool_calls_total.inc(labels)
        self.tool_call_duration.observe(duration_ms, labels)

    def record_mcp_error(self, server_id: str, error_type: str):
        self.mcp_server_errors.inc({"server_id": server_id, "error_type": error_type})

    def dump(self) -> Dict:
        """导出所有指标数据（用于 /metrics 端点）"""
        return {
            "llm_calls": self.llm_calls_total.collect(),
            "llm_response_times": self.llm_response_time.collect()[-50:],  # 最近50条
            "tool_calls": self.tool_calls_total.collect(),
            "tool_durations": self.tool_call_duration.collect()[-50:],
            "mcp_errors": self.mcp_server_errors.collect(),
            "chat_requests": self.chat_requests_total.collect(),
        }


# 全局单例
_metrics = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    return _metrics


class LLMCallTimer:
    """上下文管理器：自动记录 LLM 调用时间"""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        self.start_time = None
        self.status = "success"

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        if exc_type is not None:
            self.status = "error"
        _metrics.record_llm_call(self.provider, self.model, self.status, duration)
        return False  # 不吞异常


class ToolCallTimer:
    """上下文管理器：自动记录工具调用时间"""

    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        self.start_time = None
        self.status = "success"

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000
        if exc_type is not None:
            self.status = "error"
        _metrics.record_tool_call(self.tool_name, self.status, duration_ms)
        return False
