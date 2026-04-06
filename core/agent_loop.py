"""
自主行动循环 (Agentic Loop)
严格按照 7 步 while 循环范式实现，第一步始终在循环内部执行：

while True:
    0. [Harness] isolation_guard: 子 Agent 上下文隔离 / context_optimizer: mailbox 压缩
    1. 预处理：调用 ContextPipeline.prepare(stm, ...)
       - LTM RAG 检索（向量库语义召回历史画像/偏好）
       - 环境状态读取（当前时间、系统状态）
       - SemanticNoiseFilter（Snip + Microcompact + 格式拦截）
       - WaterfallCompressor（4 级瀑布流压缩，结果写回 stm）
       - StateOrganizer（头部锚定系统提示 + 尾部潜意识注入）
    2. 判断前提：迭代次数 / 工具次数上限 + [Harness] 插件健康度熔断
    3. 调用 LLM 推理（[Harness] sandwich_reasoning 按需拦截）
    4. 检查结果：tool_calls vs 最终回答 + [Harness] deterministic_linter 硬校验
    5. 执行工具，写回 ShortTermMemory；子 Agent 结果经 [Harness] wrap_child_agent 摘要
    6. 判断终止条件（已在 4/5 中 break）
    7. 进入下一轮

生命周期外层（不参与 while 循环）：
    - janitor_daemon  : FastAPI lifespan 中启动，后台异步清理
    - middleware_plugin_hub : __init__ 注册，提供插件开关总线
"""
import asyncio
import inspect
from datetime import datetime
from typing import List, Dict, Callable, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    ToolMessage,
)

from core.context_pipeline import ContextPipeline

MAX_ITERATIONS = 20    # 最大循环轮次
MAX_TOOL_CALLS = 10    # 单次对话最大工具调用次数

# 触发 sandwich_reasoning 的最小任务描述长度（字符）
SANDWICH_TASK_MIN_LEN = 200


class AgentLoop:
    """
    自主行动循环实例。
    每次对话调用 arun()，在 while 循环内完全自控：
    上下文预处理 → 前提判断 → LLM 推理 → 工具执行 → 记忆更新 → 终止判断。

    Harness 切面以「零侵入」方式嵌入各步骤：
      所有 harness 组件通过 middleware_plugin_hub.get_active_plugin() 按名取用，
      返回 None 时自动降级为原生逻辑，不抛异常。
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools_map: Dict[str, Callable],
        tools_schema: List[Dict],
        system_prompt: str = "",
        memory_manager=None,
        # Harness: 可选注入子 Agent 摘要用轻量 LLM（不传则跳过摘要）
        summarizer_llm: Optional[BaseChatModel] = None,
        # Harness: 当前实例是否作为子 Agent 运行（影响上下文隔离策略）
        is_child_agent: bool = False,
    ):
        self._llm = llm
        self._tools_map = tools_map
        self._tools_schema = tools_schema
        self._system_prompt = system_prompt
        self._memory_manager = memory_manager
        self._summarizer_llm = summarizer_llm
        self._is_child_agent = is_child_agent

        # 绑定工具 schema 到 LLM
        if self._tools_schema:
            self._llm_with_tools = self._llm.bind_tools(
                [s["function"] if "function" in s else s for s in self._tools_schema]
            )
        else:
            self._llm_with_tools = self._llm

        # 预处理流水线（stateless，每次对话复用同一实例）
        summary_llm = memory_manager._summary_llm if memory_manager else None
        self._pipeline = ContextPipeline(
            system_prompt=system_prompt,
            summary_llm=summary_llm,
        )

        # ── Harness: middleware_plugin_hub ────────────────────────
        # 确保默认插件已注册（模块首次 import 时会自动注册，这里作保险触发）
        try:
            from harness_framework.middleware_plugin_hub import _register_default_plugins
            _register_default_plugins()
        except Exception:
            pass

    async def arun(
        self,
        user_message: HumanMessage,
        thread_id: str,
        user_id: str = "",
        stream_ctx=None,
        # Harness: 传入父 Agent 的 messages 供 isolation_guard 使用（子 Agent 模式）
        parent_messages: Optional[List] = None,
        # Harness: 若为 sandwich 模式，可指定轻量执行 LLM（不传则用主 LLM）
        execution_llm: Optional[BaseChatModel] = None,
    ) -> str:
        """
        主入口：执行完整的自主行动循环。
        返回最终回答文本，同时通过 stream_ctx 实时推送流式事件。
        """
        iteration = 0
        tool_call_count = 0
        full_response = ""
        force_stop = False

        # ── Step 0 [Harness]: isolation_guard — 子 Agent 上下文隔离 ──
        # 若当前实例作为子 Agent 运行且父上下文已传入，则切断父历史，
        # 只保留 SystemMessage（人设 + 工具描述），防止认知污染。
        # 提取到的隔离系统消息列表将在流水线 prepare() 前注入 STM。
        isolation_base_messages: List = []
        if self._is_child_agent and parent_messages:
            try:
                from harness_framework.isolation_guard import create_isolated_context
                isolation_base_messages = create_isolated_context(
                    parent_messages, isolation_level="full"
                )
            except Exception:
                pass

        # 获取 ShortTermMemory；子 Agent 模式下先写入隔离基底（仅 SystemMessage），
        # 再写入本轮用户消息，确保父 Agent 的历史对话不进入本 STM。
        stm = await self._get_stm(thread_id)
        if isolation_base_messages:
            for base_msg in isolation_base_messages:
                stm.messages.append(base_msg)
        await stm.add_message_async(user_message)

        while True:
            iteration += 1

            # ── Step 1: 预处理 ────────────────────────────────────────
            #
            # 设计目标：像一个拥有极高洁癖的安检员，把原始记忆洗得干干净净、
            # 压得严严实实，并且绝对不破坏大模型 API 的底层语法规则。
            #
            # 直接传入 stm 对象（而非快照），流水线内部：
            #   ① 读 stm 当前状态 → 内存拷贝进行清洗
            #   ② 将压缩后的结果写回 stm（防止下轮加载数据库时垃圾复活）
            #   ③ 返回最终组装好的 messages 列表喂给 LLM
            #
            # 同时在此步骤内完成：
            #   • LTM RAG 检索：基于用户最新消息，向量语义召回历史画像/偏好
            #   • 环境状态读取：当前时间精确到秒，注入 System Prompt
            #
            # 工具写回 10 万字日志后，下一轮必经此处清洗压缩，绝不会撑爆
            #
            env_state = self._read_env_state()
            ltm_snippets = await self._retrieve_ltm(
                user_id=user_id,
                query=user_message.content if isinstance(user_message.content, str) else "",
            )
            messages_for_llm = await self._pipeline.prepare(
                stm=stm,
                env_state=env_state,
                ltm_snippets=ltm_snippets,
            )

            # ── Step 2: 判断前提 ──────────────────────────────────────
            if force_stop or iteration > MAX_ITERATIONS:
                termination_msg = f"\n[系统：已达到最大推理轮次 {MAX_ITERATIONS}，强制终止]"
                await self._push(stream_ctx, "text", content=termination_msg)
                full_response += termination_msg
                break

            # [Harness] middleware_plugin_hub — 插件健康度熔断
            # 若核心插件大面积失效（注册表损坏），拒绝继续本轮推理，防止「带病推理」
            if not self._check_plugin_health():
                err_msg = "\n[系统：核心中间件健康检查失败，本轮推理已中止]"
                await self._push(stream_ctx, "text", content=err_msg)
                full_response += err_msg
                break

            # ── Step 3: 执行核心逻辑 - 调用 LLM（真流式）────────────────
            # [Harness] sandwich_reasoning — 复杂任务算力分配
            # 触发条件：sandwich 插件已启用 + 任务描述够长（判定为复杂任务）
            # 拦截后走 大模型规划→轻模型执行→大模型验证 三段流水线；
            # 否则走 astream 真流式路径。
            user_query = user_message.content if isinstance(user_message.content, str) else ""
            sandwich = self._get_plugin("sandwich_reasoning")
            if sandwich and len(user_query) >= SANDWICH_TASK_MIN_LEN and iteration == 1:
                try:
                    exec_llm = execution_llm or self._llm
                    sandwich_result = await sandwich.arun_sandwich(
                        task_description=user_query,
                        planning_llm=self._llm,
                        execution_llm=exec_llm,
                        verification_llm=self._llm,
                    )
                    full_response = sandwich_result
                    await self._push_text_streaming(stream_ctx, sandwich_result)
                    await stm.add_message_async(AIMessage(content=sandwich_result))
                    break  # sandwich 完成即视为最终回答，退出循环
                except Exception:
                    pass  # sandwich 失败降级为普通推理

            # ── astream 真流式推理 ─────────────────────────────────────
            # 使用 astream() 逐 chunk 推送，避免等待全量响应。
            # 支持三种内容块：
            #   · think 块（<think>…</think> 或 chunk.additional_kwargs["thinking"]）
            #   · text 块（正式回答文字，打字机效果）
            #   · tool_call 块（工具调用信息，累积后在 Step 4 处理）
            # 同时过滤「<tool_call> … </tool_call>」内联格式，防止原始 JSON 泄露前端。
            response = None
            streamed_text = ""         # 累积最终文字（用于写回 STM）
            tool_calls_accumulated = []  # 累积 tool_call 增量块
            thinking_started = False   # 是否已推送过 think 块

            try:
                async for chunk in self._llm_with_tools.astream(messages_for_llm):
                    # ① 收集最终 response 对象（取最后一个有效 chunk）
                    if response is None:
                        response = chunk
                    else:
                        try:
                            response = response + chunk
                        except Exception:
                            response = chunk

                    # ② 处理 think 块（推理模型专属，如 DeepSeek-R1 / QwQ）
                    # 来源 A：chunk.additional_kwargs["thinking"]（Claude / 部分 OpenAI 兼容模型）
                    think_text = ""
                    ak = getattr(chunk, "additional_kwargs", {}) or {}
                    if ak.get("thinking"):
                        think_text = ak["thinking"]

                    # 来源 B：content 列表中 type=="thinking" 的块（Anthropic 原生格式）
                    raw_content = chunk.content if hasattr(chunk, "content") else ""
                    if isinstance(raw_content, list):
                        for block in raw_content:
                            if isinstance(block, dict) and block.get("type") == "thinking":
                                think_text += block.get("thinking", "")
                        # 只取 text 类型作为正式输出
                        text_parts = [
                            b.get("text", "") for b in raw_content
                            if isinstance(b, dict) and b.get("type") == "text"
                        ]
                        raw_content = "".join(text_parts)

                    if think_text:
                        thinking_started = True
                        await self._push(stream_ctx, "think", content=think_text)

                    # ③ 处理正式文字
                    # 内联 <tool_call> 标签可能跨多个 chunk 到来（不完整），
                    # 不能在 chunk 级过滤，先把原始文字累积到 streamed_text，
                    # 等 astream 结束后统一解析。
                    # 非 tool_call 部分实时推送，tool_call 部分暂时不推（下面做截断）。
                    if isinstance(raw_content, str) and raw_content:
                        if thinking_started:
                            thinking_started = False
                            await self._push(stream_ctx, "think_end")
                        streamed_text += raw_content
                        # 把已确定不在 <tool_call> 内的前缀实时推出去
                        safe = self._safe_prefix_outside_tool_call(raw_content)
                        if safe:
                            await self._push(stream_ctx, "text", content=safe)

                    # ④ 累积 tool_call 增量块（structured tool calling）
                    chunk_tool_calls = getattr(chunk, "tool_call_chunks", None) or []
                    for tc_chunk in chunk_tool_calls:
                        idx = tc_chunk.get("index", 0)
                        while len(tool_calls_accumulated) <= idx:
                            tool_calls_accumulated.append(
                                {"name": "", "args": "", "id": ""}
                            )
                        if tc_chunk.get("name"):
                            tool_calls_accumulated[idx]["name"] += tc_chunk["name"]
                        if tc_chunk.get("args"):
                            tool_calls_accumulated[idx]["args"] += tc_chunk["args"]
                        if tc_chunk.get("id"):
                            tool_calls_accumulated[idx]["id"] += tc_chunk["id"]

            except Exception as e:
                err_msg = f"\n[LLM 调用失败：{str(e)}]"
                await self._push(stream_ctx, "text", content=err_msg)
                full_response += err_msg
                break

            # 思考阶段结束信号（若整轮没有正式文字，也要收起思考框）
            if thinking_started:
                await self._push(stream_ctx, "think_end")

            # ── Step 4: 检查本轮结果 ──────────────────────────────────
            # 优先级：① response.tool_calls（structured） → ② tool_call_chunks 累积
            # → ③ streamed_text 内联解析（Qwen/DeepSeek 内联格式）
            import json as _json
            tool_calls = []
            if response is not None:
                tool_calls = getattr(response, "tool_calls", None) or []

            if not tool_calls and tool_calls_accumulated:
                for tc in tool_calls_accumulated:
                    if tc.get("name"):
                        try:
                            args = _json.loads(tc["args"]) if tc["args"] else {}
                        except Exception:
                            args = {}
                        tool_calls.append({"name": tc["name"], "args": args, "id": tc["id"]})

            # ③ 内联格式兜底：从 streamed_text 中提取 <tool_call>…</tool_call>
            inline_tool_calls = []
            if not tool_calls:
                inline_tool_calls = self._extract_inline_tool_calls(streamed_text)
                tool_calls = inline_tool_calls

            # 若确实有内联 tool call，streamed_text 里已经推出了带标签的脏内容，
            # 需要把纯文字部分（标签之外）重新正确推送（补差）：
            # 做法是计算 clean_text，与已推出的 streamed_text 做 diff，推送差额。
            if inline_tool_calls:
                clean_text = self._strip_inline_tool_calls(streamed_text).strip()
                # 已推出的内容比 clean_text 多了 tool_call 标签和 tag 周围文字，
                # 推一个"回退+替换"信号，让前端用 clean_text 覆盖思考区域内的脏内容。
                # 实现上：推一个 text_replace packet（新类型），前端据此整体替换。
                if clean_text:
                    await self._push(stream_ctx, "text_replace", content=clean_text)
                else:
                    # 没有纯文字（全是 tool call 描述），清空已推内容
                    await self._push(stream_ctx, "text_replace", content="")

            if not tool_calls:
                # 纯文字最终回答
                content = self._strip_inline_tool_calls(streamed_text) or (
                    response.content if response and isinstance(response.content, str)
                    else str(response.content) if response else ""
                )
                content = content.strip()

                # [Harness] deterministic_linter
                linter = self._get_plugin("deterministic_linter")
                if linter:
                    ok, reason = linter.validate_output(content, output_type="plain_text")
                    if not ok:
                        await stm.add_message_async(AIMessage(content=content))
                        await stm.add_message_async(HumanMessage(
                            content=f"[系统校验：上一条输出不合格，原因：{reason}，请重新生成]"
                        ))
                        try:
                            linter.auto_disable_if_needed(
                                error_rate=getattr(linter, "_err_count", 0) / max(iteration, 1)
                            )
                        except Exception:
                            pass
                        continue

                full_response = content
                await stm.add_message_async(AIMessage(content=content))
                break  # ── Step 6: 终止条件满足

            # ── Step 5: 更新数据 - 执行工具，写回 ShortTermMemory ──────
            # 先存带 tool_calls 的 AI 消息（保持 OpenAI 对话结构完整性）
            await stm.add_message_async(response)

            for tool_call in tool_calls:
                if tool_call_count >= MAX_TOOL_CALLS:
                    limit_msg = f"\n[系统：工具调用次数超过上限 {MAX_TOOL_CALLS}，已停止]"
                    await self._push(stream_ctx, "text", content=limit_msg)
                    full_response += limit_msg
                    force_stop = True
                    break

                tool_call_count += 1
                tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else getattr(tool_call, "name", "")
                tool_args = tool_call.get("args", {}) if isinstance(tool_call, dict) else getattr(tool_call, "args", {})
                tool_id   = tool_call.get("id", tool_name) if isinstance(tool_call, dict) else getattr(tool_call, "id", tool_name)

                await self._push(
                    stream_ctx, "tool_call_start",
                    tool_name=tool_name,
                    tool_args=tool_args,
                )

                # [Harness] isolation_guard.wrap_child_agent
                # 若被调用的工具本身是一个子 Agent（工具名以 _agent 结尾作为约定），
                # 则将其 ainvoke 包装为隔离版本：子 Agent 完整输出 → 2-3 句摘要写回父 STM。
                raw_func = self._tools_map.get(tool_name)
                if raw_func and tool_name.endswith("_agent") and self._summarizer_llm:
                    try:
                        from harness_framework.isolation_guard import wrap_child_agent

                        async def _sync_wrapper(**kw):
                            return raw_func(**kw)

                        async_func = raw_func if inspect.iscoroutinefunction(raw_func) else _sync_wrapper
                        isolated_func = wrap_child_agent(
                            async_func,
                            result_summarizer_llm=self._summarizer_llm,
                        )
                        tool_result = await isolated_func(**tool_args)
                    except Exception:
                        tool_result = await self._execute_tool(tool_name, tool_args)
                else:
                    tool_result = await self._execute_tool(tool_name, tool_args)

                await self._push(
                    stream_ctx, "tool_call_done",
                    tool_name=tool_name,
                    result_preview=str(tool_result)[:200],
                )

                # 写回 ShortTermMemory（第 1 轮写入 10 万字日志也不怕：下一轮 Step 1 会压缩）
                await stm.add_message_async(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id,
                    name=tool_name,
                ))

            # ── Step 7: 未触发终止条件，进入下一轮 ──────────────────────
            # （force_stop 为 True 时，Step 2 会在下一轮入口拦截并 break）

        # ── 循环结束：长期记忆持久化 ────────────────────────────────────
        if user_id and self._memory_manager and full_response:
            try:
                await self._memory_manager._long_term.summarize_and_save_session(
                    user_id=user_id,
                    session_messages=stm.get_messages(),
                    summary_llm=self._memory_manager._summary_llm,
                )
            except Exception:
                pass

        return full_response

    # ─────────────────────────────────────────────────────────────
    # 内部辅助方法
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _read_env_state() -> dict:
        """
        环境状态读取：获取当前物理时间（精确到秒）等系统状态，
        为 StateOrganizer 生成系统提示词提供素材。
        """
        return {
            "current_time": datetime.now().strftime("%Y年%m月%d日 %H:%M:%S"),
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()],
        }

    async def _retrieve_ltm(self, user_id: str, query: str) -> List[str]:
        """
        长期记忆 RAG 检索：
        基于用户最新消息，通过向量语义召回历史画像、事实偏好。
        底层走 VectorStore（可扩展为 BGE/Milvus/Neo4j）。
        无 user_id 或检索失败时安全降级为空列表。
        """
        if not user_id or not self._memory_manager:
            return []
        try:
            return await self._memory_manager._long_term.retrieve_relevant_memories(
                user_id=user_id,
                query=query,
                top_k=5,
            )
        except Exception:
            return []

    async def _get_stm(self, thread_id: str):
        from memory.short_term_memory import get_or_create_short_term
        summary_llm = self._memory_manager._summary_llm if self._memory_manager else None
        return await get_or_create_short_term(thread_id, summary_llm)

    async def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        func = self._tools_map.get(tool_name)
        if func is None:
            return f"[错误] 未找到工具：{tool_name}"
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**tool_args)
            else:
                result = func(**tool_args)
            return str(result) if result is not None else ""
        except Exception as e:
            return f"[工具 {tool_name} 执行失败：{str(e)}]"

    async def _push(self, stream_ctx, ptype: str, **kwargs):
        if stream_ctx is None:
            return
        await stream_ctx.write({"type": ptype, **kwargs})

    async def _push_text_streaming(self, stream_ctx, content: str):
        if stream_ctx is None:
            return
        chunk_size = 6
        for i in range(0, len(content), chunk_size):
            await stream_ctx.write({"type": "text", "content": content[i:i + chunk_size]})
            await asyncio.sleep(0)

    @staticmethod
    def _get_plugin(name: str):
        """通过 middleware_plugin_hub 取插件实例，未激活或异常均返回 None。"""
        try:
            from harness_framework.middleware_plugin_hub import get_active_plugin
            return get_active_plugin(name)
        except Exception:
            return None

    @staticmethod
    def _check_plugin_health() -> bool:
        """
        插件健康度熔断检查。
        当 plugin_hub 本身无法 import（注册表损坏）时返回 False，
        触发 Step 2 熔断，防止带病推理。正常情况始终返回 True。
        """
        try:
            from harness_framework.middleware_plugin_hub import list_plugins
            list_plugins()
            return True
        except Exception:
            return False

    @staticmethod
    def _filter_inline_tool_call(text: str) -> str:
        """
        流式 chunk 级过滤：去掉当前 chunk 中属于 <tool_call>...</tool_call> 的部分。
        采用状态机逐字符扫描，保留标签外的普通文字。
        适用于 Qwen / DeepSeek 等把 tool_call 内联在 content 里的模型。
        """
        import re
        # 快速路径：chunk 不含标签特征直接返回
        if "<tool_call>" not in text and "</tool_call>" not in text:
            return text
        # 整体正则替换（chunk 粒度够小，不会跨 chunk 拆分标签）
        return re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", text)

    @staticmethod
    def _strip_inline_tool_calls(text: str) -> str:
        """
        全文兜底过滤：用于最终 content 的完整扫描，
        去掉所有残留的内联 tool_call 块（含跨 chunk 拼合后的完整标签）。
        """
        import re
        text = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", text)
        text = re.sub(r"</?tool_call>", "", text)
        return text.strip()

    @staticmethod
    def _extract_inline_tool_calls(text: str) -> list:
        """
        从内联格式的 content 中提取所有 <tool_call>…</tool_call> 块，
        返回结构化 tool_calls 列表，格式与 response.tool_calls 一致：
          [{"name": "web_search", "args": {"query": "..."}, "id": "inline_0"}]

        支持的 JSON key 格式：
          {"name": "...", "arguments": {...}}   ← Qwen 格式
          {"name": "...", "parameters": {...}}  ← 部分其他模型
          {"name": "...", "args": {...}}        ← 标准格式
        """
        import re
        import json as _json
        result = []
        for i, m in enumerate(re.finditer(r"<tool_call>([\s\S]*?)</tool_call>", text)):
            raw = m.group(1).strip()
            try:
                obj = _json.loads(raw)
            except Exception:
                continue
            name = obj.get("name", "")
            if not name:
                continue
            args = obj.get("arguments") or obj.get("parameters") or obj.get("args") or {}
            result.append({"name": name, "args": args, "id": f"inline_{i}"})
        return result

    @staticmethod
    def _safe_prefix_outside_tool_call(chunk: str) -> str:
        """
        从单个 chunk 中取出 <tool_call> 开始标签之前的安全文字部分实时推出。
        若 chunk 中不含 <tool_call>，直接返回整个 chunk。
        若 chunk 以 <tool_call> 开头或中间含有，只返回开始标签之前的部分。
        """
        idx = chunk.find("<tool_call>")
        if idx == -1:
            return chunk
        return chunk[:idx]
