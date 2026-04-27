"""
自主行动循环 (Agentic Loop)
重构点：显式 State + transition 消费机制 + plan→tool→observation 闭环。
"""
import asyncio
import inspect
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core.context_pipeline import ContextPipeline
from core.observability import ToolCallTimer
from core.token_counter import count_str_tokens
from function_calling.fc_validator import validate_tool_call_against_schema
from skill_system.weather_skill import detect_weather_tool_args

MAX_ITERATIONS = 20
MAX_TOOL_CALLS = 10
MAX_OUTPUT_RECOVERY_LIMIT = 3
MAX_OUTPUT_ESCALATED_TOKENS = 64000
DEFAULT_MAX_BUDGET_USD = 3.0
DEFAULT_MODEL_NAME = "qwen2.5-72b"

SANDWICH_TASK_MIN_LEN = 200

TransitionType = Literal[
    "next_turn",
    "collapse_drain_retry",
    "reactive_compact_retry",
    "max_output_tokens_escalate",
    "max_output_tokens_recovery",
    "stop_hook_blocking",
    "token_budget_continuation",
]


@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def add(self, other: "UsageStats") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens


@dataclass
class ToolUseContext:
    agent_id: str
    tools: List[Dict]
    read_file_cache: Dict[str, str] = field(default_factory=dict)
    abort_controller: asyncio.Event = field(default_factory=asyncio.Event)
    on_progress: Optional[Callable[..., Any]] = None


@dataclass
class AgentState:
    messages: List[Any]
    tool_use_context: ToolUseContext
    auto_compact_tracking: Optional[Dict[str, Any]] = None
    max_output_tokens_recovery_count: int = 0
    has_attempted_reactive_compact: bool = False
    max_output_tokens_override: Optional[int] = None
    pending_tool_use_summary: Optional[asyncio.Task] = None
    stop_hook_active: Optional[bool] = None
    turn_count: int = 0
    transition: Optional[TransitionType] = None


class AgentLoop:
    def __init__(
        self,
        llm: BaseChatModel,
        tools_map: Dict[str, Callable],
        tools_schema: List[Dict],
        system_prompt: str = "",
        memory_manager=None,
        summarizer_llm: Optional[BaseChatModel] = None,
        is_child_agent: bool = False,
        model_name: str = DEFAULT_MODEL_NAME,
        max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
    ):
        self._llm = llm
        self._tools_map = tools_map
        self._tools_schema = tools_schema
        self._system_prompt = system_prompt
        self._memory_manager = memory_manager
        self._summarizer_llm = summarizer_llm
        self._is_child_agent = is_child_agent
        self._model_name = model_name
        self._max_budget_usd = max_budget_usd

        if self._tools_schema:
            self._llm_with_tools = self._llm.bind_tools(
                [s["function"] if "function" in s else s for s in self._tools_schema]
            )
        else:
            self._llm_with_tools = self._llm

        summary_llm = memory_manager._summary_llm if memory_manager else None
        self._pipeline = ContextPipeline(system_prompt=system_prompt, summary_llm=summary_llm)

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
        parent_messages: Optional[List] = None,
        execution_llm: Optional[BaseChatModel] = None,
    ) -> str:
        full_response = ""
        force_stop = False
        tool_call_count = 0
        total_usage = UsageStats()

        isolation_base_messages: List = []
        if self._is_child_agent and parent_messages:
            try:
                from harness_framework.isolation_guard import create_isolated_context
                isolation_base_messages = create_isolated_context(parent_messages, isolation_level="full")
            except Exception:
                pass

        stm = await self._get_stm(thread_id)
        if isolation_base_messages:
            for base_msg in isolation_base_messages:
                stm.messages.append(base_msg)
        await stm.add_message_async(user_message)

        state = AgentState(
            messages=stm.get_messages(),
            tool_use_context=ToolUseContext(
                agent_id=f"agent-{thread_id}",
                tools=self._tools_schema,
            ),
        )

        routed_response = await self._try_direct_weather_skill_route(
            user_message=user_message,
            stm=stm,
            stream_ctx=stream_ctx,
        )
        if routed_response is not None:
            return routed_response

        routed_response = await self._try_direct_date_route(
            user_message=user_message,
            stm=stm,
            stream_ctx=stream_ctx,
        )
        if routed_response is not None:
            return routed_response

        while True:
            consumed_transition = state.transition
            state.transition = None
            if consumed_transition:
                await self._push(
                    stream_ctx,
                    "loop_status",
                    phase="transition",
                    status="running",
                    message=f"消费 transition: {consumed_transition}",
                )

            if consumed_transition == "reactive_compact_retry":
                state.max_output_tokens_override = MAX_OUTPUT_ESCALATED_TOKENS

            if force_stop or state.turn_count >= MAX_ITERATIONS:
                msg = f"\n[系统：已达到最大推理轮次 {MAX_ITERATIONS}，强制终止]"
                await self._push(stream_ctx, "text", content=msg)
                full_response += msg
                break

            if tool_call_count >= MAX_TOOL_CALLS:
                msg = f"\n[系统：工具调用次数超过上限 {MAX_TOOL_CALLS}，已停止]"
                await self._push(stream_ctx, "text", content=msg)
                full_response += msg
                break

            if self._estimate_total_cost(total_usage) >= self._max_budget_usd:
                msg = f"\n[系统：预算已达 ${self._estimate_total_cost(total_usage):.4f}，停止执行]"
                await self._push(stream_ctx, "text", content=msg)
                full_response += msg
                break

            if not self._check_plugin_health():
                msg = "\n[系统：核心中间件健康检查失败，本轮推理已中止]"
                await self._push(stream_ctx, "text", content=msg)
                full_response += msg
                break

            await self._push(stream_ctx, "loop_status", phase="compact_check", status="running", message="上下文压缩检查")
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
            state.messages = list(messages_for_llm)
            await self._push(stream_ctx, "loop_status", phase="compact_check", status="done", message="压缩检查完成")

            user_query = user_message.content if isinstance(user_message.content, str) else ""
            sandwich = self._get_plugin("sandwich_reasoning")
            if sandwich and state.turn_count == 0:
                try:
                    await self._push(stream_ctx, "loop_status", phase="plan", status="running", message="进入规划模式")
                    exec_llm = execution_llm or self._llm
                    sandwich_result = await sandwich.arun_sandwich(
                        task_description=user_query,
                        planning_llm=self._llm,
                        execution_llm=exec_llm,
                        verification_llm=self._llm,
                    )
                    if isinstance(sandwich_result, str) and sandwich_result.strip().startswith("<PLAN>"):
                        await stm.add_message_async(AIMessage(content=sandwich_result))
                        await self._push(stream_ctx, "loop_status", phase="plan", status="done", message="规划阶段完成，进入执行循环")
                    else:
                        full_response = sandwich_result
                        await self._push_text_streaming(stream_ctx, sandwich_result)
                        await stm.add_message_async(AIMessage(content=sandwich_result))
                        await self._push(stream_ctx, "loop_status", phase="plan", status="done", message="规划阶段完成")
                        break
                except Exception:
                    await self._push(stream_ctx, "loop_status", phase="plan", status="error", message="规划阶段失败，降级常规循环")

            await self._push(stream_ctx, "loop_status", phase="llm", status="running", message="调用模型进行推理")
            llm_result = await self._invoke_llm_streaming(
                state=state,
                messages_for_llm=messages_for_llm,
                stream_ctx=stream_ctx,
            )
            llm_status = llm_result.get("llm_status", "done")
            if llm_status == "error":
                await self._push(stream_ctx, "loop_status", phase="llm", status="error", message="模型推理失败")
            else:
                await self._push(stream_ctx, "loop_status", phase="llm", status="done", message="模型推理完成")

            total_usage.add(llm_result["usage"])
            await self._push(
                stream_ctx,
                "usage_update",
                usage={
                    "input_tokens": total_usage.input_tokens,
                    "output_tokens": total_usage.output_tokens,
                    "cache_read_input_tokens": total_usage.cache_read_input_tokens,
                    "cache_creation_input_tokens": total_usage.cache_creation_input_tokens,
                    "estimated_cost_usd": self._estimate_total_cost(total_usage),
                },
            )

            if llm_result["need_retry"]:
                continue

            response = llm_result["response"]
            tool_calls = llm_result["tool_calls"]
            assistant_text = llm_result["assistant_text"]

            if response is not None:
                await stm.add_message_async(response)

            if not tool_calls:
                content = assistant_text.strip()
                if llm_status == "error":
                    full_response = content
                    await self._push(stream_ctx, "control", status="error", full_response=full_response)
                    break

                linter = self._get_plugin("deterministic_linter")
                if linter:
                    ok, reason = linter.validate_output(content, output_type="plain_text")
                    if not ok:
                        await stm.add_message_async(AIMessage(content=content))
                        await stm.add_message_async(HumanMessage(content=f"[系统校验：上一条输出不合格，原因：{reason}，请重新生成]"))
                        state.transition = "next_turn"
                        continue

                full_response = content
                await stm.add_message_async(AIMessage(content=content))
                break

            await self._push(stream_ctx, "loop_status", phase="tool", status="running", message="执行工具调用")

            for tool_call in tool_calls:
                if tool_call_count >= MAX_TOOL_CALLS:
                    force_stop = True
                    break

                tool_call_count += 1
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", tool_name)

                await self._push(
                    stream_ctx,
                    "tool_call_start",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call_id=tool_id,
                )

                valid_call, validation_reason, normalized_args = validate_tool_call_against_schema(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tools_schema=self._tools_schema,
                    tools_map=self._tools_map,
                )

                if not valid_call:
                    tool_result = f"[错误] 工具调用参数校验失败：{validation_reason}。请根据工具 schema 重新生成该 function call。"
                    is_error = True
                    await self._push(
                        stream_ctx,
                        "loop_status",
                        phase="tool_lint",
                        status="error",
                        message=f"{tool_name} 参数校验失败：{validation_reason}",
                    )
                else:
                    await self._push(
                        stream_ctx,
                        "loop_status",
                        phase="tool_lint",
                        status="done",
                        message=f"{tool_name} 参数校验通过",
                    )
                    with ToolCallTimer(tool_name):
                        tool_result = await self._execute_tool(tool_name, normalized_args)
                    normalized_result, is_error = self._normalize_tool_result(tool_result)

                if not valid_call:
                    normalized_result = tool_result

                await self._push(
                    stream_ctx,
                    "tool_call_done",
                    tool_name=tool_name,
                    result_preview=str(normalized_result)[:200],
                    tool_call_id=tool_id,
                )

                await stm.add_message_async(
                    ToolMessage(
                        content=str(normalized_result),
                        tool_call_id=tool_id,
                        name=tool_name,
                    )
                )

                await self._push(
                    stream_ctx,
                    "observation",
                    tool_use_id=tool_id,
                    tool_name=tool_name,
                    is_error=is_error,
                    content_preview=str(normalized_result)[:200],
                )

            await self._push(stream_ctx, "loop_status", phase="tool", status="done", message="工具执行完成")
            state.transition = "next_turn"

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

    async def _try_direct_date_route(self, user_message: HumanMessage, stm, stream_ctx=None) -> Optional[str]:
        """Answer simple current date/day questions locally so they do not depend on LLM/API availability."""

        user_query = user_message.content if isinstance(user_message.content, str) else ""
        text = user_query.strip()
        if not text:
            return None

        compact = re.sub(r"\s+", "", text)
        date_intents = (
            "今天是什么日子",
            "今天几号",
            "今天日期",
            "今天星期几",
            "现在日期",
            "当前日期",
            "今天是哪天",
        )
        if not any(intent in compact for intent in date_intents):
            return None

        now = datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        msg = (
            f"今天是 {now.strftime('%Y年%m月%d日')}，{weekdays[now.weekday()]}。"
            "如果你想问节日/纪念日/农历等，我可以再帮你查询或计算。"
        )
        await self._push_text_streaming(stream_ctx, msg)
        await stm.add_message_async(AIMessage(content=msg))
        return msg

    async def _try_direct_weather_skill_route(self, user_message: HumanMessage, stm, stream_ctx=None) -> Optional[str]:
        """
        Weather is a canonical package skill and should not be answered by
        generic web search. For obvious weather queries, deterministically call
        skill_weather before the LLM has a chance to choose the wrong tool.
        """

        user_query = user_message.content if isinstance(user_message.content, str) else ""
        routed_args = detect_weather_tool_args(user_query)
        if routed_args is None:
            return None
        if "skill_weather" not in self._tools_map:
            return None

        if routed_args.get("__missing_location"):
            msg = "你想查询哪里的天气？请告诉我城市、地区或机场代码，例如：北京、上海、New York。"
            await self._push_text_streaming(stream_ctx, msg)
            await stm.add_message_async(AIMessage(content=msg))
            return msg

        tool_name = "skill_weather"
        tool_id = "routed_skill_weather"

        await self._push(
            stream_ctx,
            "loop_status",
            phase="skill_route",
            status="done",
            message="检测到天气意图，优先调用内置 Weather Skill",
        )
        await self._push(
            stream_ctx,
            "tool_call_start",
            tool_name=tool_name,
            tool_args=routed_args,
            tool_call_id=tool_id,
        )

        valid_call, validation_reason, normalized_args = validate_tool_call_against_schema(
            tool_name=tool_name,
            tool_args=routed_args,
            tools_schema=self._tools_schema,
            tools_map=self._tools_map,
        )
        if not valid_call:
            result = f"[错误] Weather Skill 参数校验失败：{validation_reason}"
            is_error = True
            await self._push(
                stream_ctx,
                "loop_status",
                phase="tool_lint",
                status="error",
                message=f"{tool_name} 参数校验失败：{validation_reason}",
            )
        else:
            await self._push(
                stream_ctx,
                "loop_status",
                phase="tool_lint",
                status="done",
                message=f"{tool_name} 参数校验通过",
            )
            with ToolCallTimer(tool_name):
                raw_result = await self._execute_tool(tool_name, normalized_args)
            result, is_error = self._normalize_tool_result(raw_result)

        await self._push(
            stream_ctx,
            "tool_call_done",
            tool_name=tool_name,
            result_preview=str(result)[:200],
            tool_call_id=tool_id,
        )
        await self._push(
            stream_ctx,
            "observation",
            tool_use_id=tool_id,
            tool_name=tool_name,
            is_error=is_error,
            content_preview=str(result)[:200],
        )

        await stm.add_message_async(
            ToolMessage(
                content=str(result),
                tool_call_id=tool_id,
                name=tool_name,
            )
        )

        if is_error:
            final = str(result)
        else:
            final = f"查询结果如下：\n\n{result}"
        await self._push_text_streaming(stream_ctx, final)
        await stm.add_message_async(AIMessage(content=final))
        return final

    async def _invoke_llm_streaming(
        self,
        state: AgentState,
        messages_for_llm: List[Any],
        stream_ctx=None,
    ) -> Dict[str, Any]:
        state.turn_count += 1

        usage = UsageStats(
            input_tokens=sum(count_str_tokens(self._safe_content(m)) for m in messages_for_llm),
            output_tokens=0,
        )

        response = None
        streamed_text = ""
        tool_calls_accumulated = []
        thinking_started = False
        stop_reason = ""

        try:
            async def _consume_stream():
                nonlocal response, streamed_text, tool_calls_accumulated, thinking_started, usage
                async for chunk in self._llm_with_tools.astream(messages_for_llm):
                    if response is None:
                        response = chunk
                    else:
                        try:
                            response = response + chunk
                        except Exception:
                            response = chunk

                    ak = getattr(chunk, "additional_kwargs", {}) or {}
                    think_text = ak.get("thinking", "")
                    raw_content = chunk.content if hasattr(chunk, "content") else ""

                    if isinstance(raw_content, list):
                        text_parts = []
                        for block in raw_content:
                            if isinstance(block, dict) and block.get("type") == "thinking":
                                think_text += block.get("thinking", "")
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                        raw_content = "".join(text_parts)

                    if think_text:
                        thinking_started = True
                        await self._push(stream_ctx, "think", content=think_text)

                    if isinstance(raw_content, str) and raw_content:
                        if thinking_started:
                            thinking_started = False
                            await self._push(stream_ctx, "think_end")
                        streamed_text += raw_content
                        safe = self._safe_prefix_outside_tool_call(raw_content)
                        if safe:
                            await self._push(stream_ctx, "text", content=safe)
                            usage.output_tokens += count_str_tokens(safe)

                    chunk_tool_calls = getattr(chunk, "tool_call_chunks", None) or []
                    for tc_chunk in chunk_tool_calls:
                        idx = tc_chunk.get("index", 0)
                        while len(tool_calls_accumulated) <= idx:
                            tool_calls_accumulated.append({"name": "", "args": "", "id": ""})
                        if tc_chunk.get("name"):
                            tool_calls_accumulated[idx]["name"] += tc_chunk["name"]
                        if tc_chunk.get("args"):
                            tool_calls_accumulated[idx]["args"] += tc_chunk["args"]
                        if tc_chunk.get("id"):
                            tool_calls_accumulated[idx]["id"] += tc_chunk["id"]

            await asyncio.wait_for(_consume_stream(), timeout=90)

            if thinking_started:
                await self._push(stream_ctx, "think_end")

            tool_calls = []
            if response is not None:
                tool_calls = getattr(response, "tool_calls", None) or []

            if not tool_calls and tool_calls_accumulated:
                for tc in tool_calls_accumulated:
                    if tc.get("name"):
                        try:
                            args = json.loads(tc["args"]) if tc["args"] else {}
                        except Exception as exc:
                            args = {
                                "__raw_args": tc.get("args", ""),
                                "__parse_error": str(exc),
                            }
                        tool_calls.append({"name": tc["name"], "args": args, "id": tc["id"]})

            inline_tool_calls = []
            if not tool_calls:
                inline_tool_calls = self._extract_inline_tool_calls(streamed_text)
                tool_calls = inline_tool_calls

            if inline_tool_calls:
                clean_text = self._strip_inline_tool_calls(streamed_text).strip()
                await self._push(stream_ctx, "text_replace", content=clean_text)

            meta = getattr(response, "response_metadata", {}) if response else {}
            token_usage = meta.get("token_usage", {}) if isinstance(meta, dict) else {}
            usage.input_tokens = token_usage.get("prompt_tokens", usage.input_tokens)
            usage.output_tokens = token_usage.get("completion_tokens", usage.output_tokens)

            stop_reason = str(meta.get("finish_reason", "")) if isinstance(meta, dict) else ""
            if stop_reason == "length":
                if state.max_output_tokens_override is None:
                    state.max_output_tokens_override = MAX_OUTPUT_ESCALATED_TOKENS
                    state.transition = "max_output_tokens_escalate"
                    return {
                        "response": None,
                        "assistant_text": "",
                        "tool_calls": [],
                        "usage": usage,
                        "need_retry": True,
                        "llm_status": "done",
                    }
                state.max_output_tokens_recovery_count += 1
                if state.max_output_tokens_recovery_count <= MAX_OUTPUT_RECOVERY_LIMIT:
                    state.transition = "max_output_tokens_recovery"
                    return {
                        "response": None,
                        "assistant_text": "",
                        "tool_calls": [],
                        "usage": usage,
                        "need_retry": True,
                        "llm_status": "done",
                    }

            assistant_text = self._strip_inline_tool_calls(streamed_text)
            return {
                "response": response,
                "assistant_text": assistant_text,
                "tool_calls": tool_calls,
                "usage": usage,
                "need_retry": False,
                "llm_status": "done",
            }

        except asyncio.TimeoutError:
            if thinking_started:
                await self._push(stream_ctx, "think_end")
            await self._push(stream_ctx, "text", content="\n[LLM 超时：90秒内未返回，已中止本轮并回退]")
            return {
                "response": None,
                "assistant_text": "",
                "tool_calls": [],
                "usage": usage,
                "need_retry": False,
                "llm_status": "error",
            }

        except Exception as e:
            err = str(e)
            safe_err = self._sanitize_llm_error(err)
            if "context" in err.lower() and "length" in err.lower() and not state.has_attempted_reactive_compact:
                if thinking_started:
                    await self._push(stream_ctx, "think_end")
                state.has_attempted_reactive_compact = True
                state.transition = "reactive_compact_retry"
                return {
                    "response": None,
                    "assistant_text": "",
                    "tool_calls": [],
                    "usage": usage,
                    "need_retry": True,
                }

            if thinking_started:
                await self._push(stream_ctx, "think_end")
            error_text = f"\n[LLM 调用失败：{safe_err}]"
            await self._push(stream_ctx, "text", content=error_text)
            return {
                "response": None,
                "assistant_text": error_text,
                "tool_calls": [],
                "usage": usage,
                "need_retry": False,
                "llm_status": "error",
            }

    def _normalize_tool_result(self, tool_result: Any) -> Tuple[str, bool]:
        if isinstance(tool_result, str):
            txt = tool_result
        else:
            txt = json.dumps(tool_result, ensure_ascii=False) if isinstance(tool_result, (dict, list)) else str(tool_result)

        is_error = txt.startswith("[错误]") or "执行失败" in txt
        if len(txt) > 50000:
            txt = txt[:2000] + "\n... [工具输出过大，已截断]"
        return txt, is_error

    @staticmethod
    def _safe_content(msg: Any) -> str:
        content = getattr(msg, "content", "")
        return content if isinstance(content, str) else str(content)

    @staticmethod
    def _estimate_total_cost(total_usage: UsageStats) -> float:
        # 统一估价：仅用于预算守卫，非账单精算
        input_price = 0.000002
        output_price = 0.000010
        cache_read_price = 0.0000002
        cache_creation_price = 0.0000025

        return (
            total_usage.input_tokens * input_price
            + total_usage.output_tokens * output_price
            + total_usage.cache_read_input_tokens * cache_read_price
            + total_usage.cache_creation_input_tokens * cache_creation_price
        )

    @staticmethod
    def _read_env_state() -> dict:
        return {
            "current_time": datetime.now().strftime("%Y年%m月%d日 %H:%M:%S"),
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()],
        }

    async def _retrieve_ltm(self, user_id: str, query: str) -> List[str]:
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
            if tool_name == "read_file" and isinstance(tool_args, dict):
                path = tool_args.get("file_path")
                if path in (None, ""):
                    return "[错误] read_file 缺少 file_path"

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
        try:
            from harness_framework.middleware_plugin_hub import get_active_plugin
            return get_active_plugin(name)
        except Exception:
            return None

    @staticmethod
    def _check_plugin_health() -> bool:
        try:
            from harness_framework.middleware_plugin_hub import list_plugins
            list_plugins()
            return True
        except Exception:
            return False

    @staticmethod
    def _strip_inline_tool_calls(text: str) -> str:
        import re
        text = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", text)
        text = re.sub(r"</?tool_call>", "", text)
        return text.strip()

    @staticmethod
    def _extract_inline_tool_calls(text: str) -> list:
        import re
        result = []
        for i, m in enumerate(re.finditer(r"<tool_call>([\s\S]*?)</tool_call>", text)):
            raw = m.group(1).strip()
            try:
                obj = json.loads(raw)
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
        idx = chunk.find("<tool_call>")
        if idx == -1:
            return chunk
        return chunk[:idx]

    def _sanitize_llm_error(self, err: str) -> str:
        raw = err or ""
        lower = raw.lower()
        if "<!doctype" in lower or "<html" in lower or "websaas" in lower:
            if "黑名单" in raw or "禁止访问" in raw or "vpn" in lower or "校园网" in raw:
                model_name = getattr(self, "_model_name", "unknown")
                return (
                    f"模型 API 网关返回了 HTML 黑名单/禁止访问页面，当前模型 {model_name} 的接口可能需要 VPN/校园网，"
                    "或者当前出口 IP 被网关拦截。请检查 .env 里的 LLM_ENDPOINT__/LLM_API_KEY__ 配置，"
                    "切换到可访问的模型接口，或连接校园网/VPN 后重启服务。"
                )
            title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
            title_text = re.sub(r"\s+", " ", title.group(1)).strip() if title else "HTML response"
            return (
                f"模型 API 返回了非 JSON 的 HTML 页面（{title_text}），说明 LLM endpoint/base_url 可能配置错误或被代理/网关拦截。"
            )
        if len(raw) > 800:
            return raw[:800] + "...[已截断]"
        return raw
