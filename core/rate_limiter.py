"""
流量限速器 - 基于内存的滑动窗口限速（无需 Redis）
防止恶意高频请求导致 LLM API 费用爆炸
"""
import time
from collections import defaultdict, deque
from typing import Dict, Optional
import asyncio


# 全局限速配置
RATE_LIMITS: Dict[str, Dict] = {
    "/api/chat/stream": {"requests": 20, "window_seconds": 60},
    "/api/mcp/servers": {"requests": 100, "window_seconds": 60},
    "default": {"requests": 60, "window_seconds": 60},
}


class RateLimiter:
    """内存滑动窗口限速器（适合单进程部署，无需 Redis）"""

    def __init__(self):
        # user_id:endpoint -> deque of timestamps
        self._windows: Dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check_rate_limit(
        self,
        user_id: str,
        endpoint: str,
        is_admin: bool = False,
    ) -> bool:
        """
        检查是否超过限速。
        返回 True 表示允许通过，False 表示被限速。
        admin 用户豁免限速。
        """
        if is_admin:
            return True

        config = RATE_LIMITS.get(endpoint, RATE_LIMITS["default"])
        max_requests = config["requests"]
        window_seconds = config["window_seconds"]

        key = f"{user_id}:{endpoint}"
        now = time.monotonic()
        window_start = now - window_seconds

        async with self._lock:
            q = self._windows[key]
            # 移除窗口外的旧记录
            while q and q[0] < window_start:
                q.popleft()

            if len(q) >= max_requests:
                return False  # 超限

            q.append(now)
            return True

    def sync_check(self, user_id: str, endpoint: str, is_admin: bool = False) -> bool:
        """同步版本（不用于异步上下文）"""
        if is_admin:
            return True
        config = RATE_LIMITS.get(endpoint, RATE_LIMITS["default"])
        max_requests = config["requests"]
        window_seconds = config["window_seconds"]

        key = f"{user_id}:{endpoint}"
        now = time.monotonic()
        window_start = now - window_seconds

        q = self._windows[key]
        while q and q[0] < window_start:
            q.popleft()

        if len(q) >= max_requests:
            return False

        q.append(now)
        return True


# 全局单例
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


async def rate_limit_check(user_id: str, endpoint: str, is_admin: bool = False):
    """FastAPI Depends 用的限速检查函数"""
    from fastapi import HTTPException
    limiter = get_rate_limiter()
    allowed = await limiter.check_rate_limit(user_id, endpoint, is_admin)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁，请稍后再试（{endpoint} 限速：{RATE_LIMITS.get(endpoint, RATE_LIMITS['default'])['requests']}次/分钟）"
        )
