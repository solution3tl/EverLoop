"""
MCP Agent - 将 MCP Server 包装成工具化身
本身也是一个轻量 Agent，对外呈现为 @tool 函数
"""
from typing import Optional

from langchain_core.language_models import BaseChatModel

from database.models import MCPServer
from mcp_ecosystem import pipeline_manager
from mcp_ecosystem import server_manager


class MCPAgent:
    """
    将单个 MCP Server 包装为可调用的子 Agent。
    通过 general_agent.py 包装为 @tool 注册到主 Agent 的工具列表。
    """

    def __init__(
        self,
        llm: BaseChatModel,
        mcp_server: MCPServer,
        enabled_memory: bool = False,
        knowledge_store_id: Optional[str] = None,
    ):
        self.llm = llm
        self.mcp_server = mcp_server
        self.enabled_memory = enabled_memory
        self.knowledge_store_id = knowledge_store_id
        self._tools_schema = []
        self._initialized = False

    async def _prepare_context(self):
        """初始化时调用一次：获取工具 Schema、加载记忆"""
        if self._initialized:
            return

        # 获取该 Server 的工具列表（非权限校验，admin 模式）
        try:
            schema, _ = await server_manager.parse_server_tools_schema(
                server_id=str(self.mcp_server.id),
                requester_id=str(self.mcp_server.owner_id),
                is_admin=True,
            )
            self._tools_schema = schema
        except Exception as e:
            print(f"[WARN] MCPAgent {self.mcp_server.name} 获取工具 Schema 失败：{e}")

        # 若开启记忆，预加载历史
        if self.enabled_memory:
            try:
                from memory.long_term_memory import retrieve_relevant_memories
                # 无法在初始化时知道 user_id，此处跳过
            except Exception:
                pass

        self._initialized = True

    async def ainvoke(
        self,
        user_query: str,
        parent_thread_id: str = "",
    ) -> str:
        """
        主入口：执行 MCP 五步流水线，返回结果摘要。
        parent_thread_id 由调用方从 ContextVar _thread_id_var 读取后传入。
        子 Agent 使用独立的 child_thread_id，不污染父 Agent 记忆空间。
        """
        await self._prepare_context()

        # 子 Agent 上下文隔离
        child_thread_id = f"{parent_thread_id}:mcp:{self.mcp_server.id}"

        # 获取当前请求的 stream_writer
        from core.middleware import get_stream_writer
        writer = get_stream_writer()

        # 执行流水线
        result = await pipeline_manager.arun_pipeline(
            mcp_server=self.mcp_server,
            user_query=user_query,
            tools_schema=self._tools_schema,
            llm=self.llm,
            stream_writer=writer,
        )
        return result
