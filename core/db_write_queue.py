"""
异步数据库写回队列 (DB Write Queue)
────────────────────────────────────────────────────────────────
设计原则（读写分离 + 事件驱动写）：

  AgentLoop 在高频 while 循环中绝不直接 await db.execute(...)。
  所有持久化动作（Snip 内容替换、记忆折叠标记）都先以事件形式
  投入本队列，由后台 Worker 协程异步消费，保证数据最终一致性
  的同时，让 LLM 推理零等待。

事件类型：
  SnipEvent  — 将某条 Message 的 content 替换为墓碑占位符
  FoldEvent  — 将一批 Message 标记为 is_folded = True
"""
import asyncio
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


# ══════════════════════════════════════════════════════════════════
# 事件定义
# ══════════════════════════════════════════════════════════════════

class EventType(Enum):
    SNIP = "snip"
    FOLD = "fold"


@dataclass
class SnipEvent:
    """Snip / Microcompact：替换单条消息内容为占位符"""
    event_type: EventType = field(default=EventType.SNIP, init=False)
    msg_id: str = ""
    placeholder: str = "[系统回收：原始内容过长已被 Snip 清理，核心逻辑已在后续对话中体现]"


@dataclass
class FoldEvent:
    """记忆折叠：批量标记消息为 is_folded = True"""
    event_type: EventType = field(default=EventType.FOLD, init=False)
    msg_ids: List[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════
# 队列单例 + 后台 Worker
# ══════════════════════════════════════════════════════════════════

_queue: asyncio.Queue = asyncio.Queue()
_worker_task: Optional[asyncio.Task] = None


def get_db_write_queue() -> asyncio.Queue:
    return _queue


def emit_snip(msg_id: str, placeholder: str = "") -> None:
    """
    投递 Snip 事件（同步，不阻塞）。
    在 AgentLoop 预处理阶段判定需要 Snip 时调用。
    """
    event = SnipEvent(msg_id=msg_id)
    if placeholder:
        event.placeholder = placeholder
    _queue.put_nowait(event)


def emit_fold(msg_ids: List[str]) -> None:
    """
    投递 Fold 事件（同步，不阻塞）。
    在 AgentLoop 预处理阶段触发记忆折叠时调用。
    """
    if msg_ids:
        _queue.put_nowait(FoldEvent(msg_ids=msg_ids))


async def _worker():
    """
    后台 Worker 协程：持续消费队列，执行实际数据库写入。
    每次批量处理，避免高频单条提交。
    """
    from database import crud

    BATCH_INTERVAL = 2.0   # 秒：攒满此时间再批量提交
    BATCH_MAX      = 50    # 每批最多处理条目数

    while True:
        batch = []
        try:
            # 等待第一个事件
            first = await asyncio.wait_for(_queue.get(), timeout=BATCH_INTERVAL)
            batch.append(first)
            # 非阻塞地排空当前已有事件（最多 BATCH_MAX - 1 条）
            while len(batch) < BATCH_MAX:
                try:
                    item = _queue.get_nowait()
                    batch.append(item)
                except asyncio.QueueEmpty:
                    break
        except asyncio.TimeoutError:
            continue  # 队列为空，继续等待

        # 按类型分组，批量执行
        snip_events = [e for e in batch if isinstance(e, SnipEvent)]
        fold_events  = [e for e in batch if isinstance(e, FoldEvent)]

        for ev in snip_events:
            try:
                await crud.snip_message_content(ev.msg_id, ev.placeholder)
            except Exception:
                pass  # 写回失败不影响 AgentLoop，仅内存状态已清洗

        # 合并所有 FoldEvent 的 msg_ids，一次性提交
        all_fold_ids = []
        for ev in fold_events:
            all_fold_ids.extend(ev.msg_ids)
        if all_fold_ids:
            try:
                await crud.fold_messages(all_fold_ids)
            except Exception:
                pass


async def start_db_write_worker():
    """
    启动后台 Worker（在 FastAPI lifespan 中调用一次）。
    幂等：重复调用不会创建多个 Worker。
    """
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker())
    return _worker_task


def stop_db_write_worker():
    """关闭 Worker（在 FastAPI shutdown 时调用）"""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
