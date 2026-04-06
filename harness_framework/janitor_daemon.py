"""
熵治理守护进程 - 后台常驻清理 Agent
定期维护文档与代码同步、清理过期数据
在 main.py 的 lifespan 钩子中以 asyncio 后台任务启动
"""
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def cleanup_inactive_sessions():
    """清理超过 7 天未活跃的会话（每小时执行）"""
    while True:
        try:
            await asyncio.sleep(3600)  # 1 小时
            from database.session_store import get_session_store
            store = get_session_store()
            count = await store.cleanup_inactive_sessions(inactivity_days=7)
            if count > 0:
                logger.info(f"[Janitor] 清理了 {count} 个过期会话")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[Janitor] cleanup_inactive_sessions 异常：{e}")


async def cleanup_expired_memories():
    """删除过期记忆记录（每天凌晨 2 点执行）"""
    while True:
        try:
            # 计算到下一个凌晨 2 点的等待时间
            now = datetime.now()
            next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run = next_run.replace(day=next_run.day + 1)
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            from database import crud
            count = await crud.delete_expired_memories()
            if count > 0:
                logger.info(f"[Janitor] 清理了 {count} 条过期记忆")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[Janitor] cleanup_expired_memories 异常：{e}")


async def cleanup_stale_mcp_servers():
    """禁用超过 30 天未使用的 MCP Server（每天凌晨 3 点）"""
    while True:
        try:
            now = datetime.now()
            next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run = next_run.replace(day=next_run.day + 1)
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            try:
                from mcp_ecosystem.server_manager import cleanup_stale_servers
                count = await cleanup_stale_servers(stale_days=30)
                if count > 0:
                    logger.info(f"[Janitor] 禁用了 {count} 个过期 MCP Server")
            except ImportError:
                pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[Janitor] cleanup_stale_mcp_servers 异常：{e}")


async def sync_knowledge_docs():
    """每周一检查知识库一致性（仅记录日志，不自动修复）"""
    while True:
        try:
            await asyncio.sleep(7 * 24 * 3600)  # 7 天
            logger.info("[Janitor] 知识库一致性检查（当前为记录模式，不自动修复）")
            from database.vector_store import get_vector_store
            vs = get_vector_store()
            collections = vs.list_collections()
            logger.info(f"[Janitor] 当前向量库集合：{collections}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[Janitor] sync_knowledge_docs 异常：{e}")


async def start_janitor():
    """启动所有守护任务（在 lifespan 中调用）"""
    tasks = [
        asyncio.create_task(cleanup_inactive_sessions(), name="janitor_sessions"),
        asyncio.create_task(cleanup_expired_memories(), name="janitor_memories"),
        asyncio.create_task(cleanup_stale_mcp_servers(), name="janitor_mcp"),
        asyncio.create_task(sync_knowledge_docs(), name="janitor_docs"),
    ]
    logger.info("[Janitor] 后台清理守护进程已启动")
    return tasks
