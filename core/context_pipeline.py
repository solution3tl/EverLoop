"""
上下文预处理流水线 (Context Prep-Pipeline)
════════════════════════════════════════════════════════════════════
AgentLoop while 循环第一步的唯一入口：ContextPipeline.prepare()

设计目标：像一个拥有极高洁癖的安检员，把原始记忆洗得干干净净、
压得严严实实，并且绝对不破坏大模型 API 的底层语法规则。

内部三模块单向流水：
  模块一  SemanticNoiseFilter    — 语义级噪音过滤（Snip / Microcompact / 格式拦截）
  模块二  WaterfallCompressor    — 瀑布流动态水位压缩（4 级卡点）
  模块三  StateOrganizer         — 状态整理与潜意识注入

数据库联动（读写分离）：
  所有内存清洗动作产生的持久化需求（Snip 内容替换、折叠标记）
  通过 core.db_write_queue 以"投递事件 → 后台 Worker 异步消费"
  的方式落库，绝不在 AgentLoop 的高频循环中同步阻塞 I/O。
════════════════════════════════════════════════════════════════════
"""
import re
from dataclasses import dataclass, field
from typing import List, Tuple

from langchain_core.messages import (
    BaseMessage,
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from core.token_counter import count_tokens, count_str_tokens

# ── Token 水位线配置 ─────────────────────────────────────────────
TOKEN_BUDGET       = 128000   # 总预算（可通过构造参数覆盖）
TOKEN_WARN_RATIO   = 0.70   # 70%  卡点 1：历史工具重度摘要
TOKEN_DANGER_RATIO = 0.85   # 85%  卡点 2：记忆折叠
TOKEN_FATAL_RATIO  = 1.00   # 100% 卡点 3：极端超载截断

# ── Snip / Microcompact 配置 ─────────────────────────────────────
SNIP_MIN_ROUNDS_AGO = 2         # 超过 N 轮前的 ToolMessage 才 Snip
SNIP_TOKEN_THRESHOLD = 300      # ToolMessage 超过此 Token 数才 Snip
TOOL_COMPRESS_THRESHOLD = 2000  # 卡点 1 压缩的阈值（防止性能倒挂）
MICROCOMPACT_WINDOW = 3         # 连续失败 N 次触发 Microcompact

# ── 折叠区保护配置 ───────────────────────────────────────────────
FOLD_ANCHOR_TYPE = HumanMessage  # 切割锚点类型：从中间向上找最近的 HumanMessage


# ══════════════════════════════════════════════════════════════════
# 流水线内部上下文快照
# ══════════════════════════════════════════════════════════════════

@dataclass
class PipelineContext:
    """模块间传递的上下文快照（内存拷贝，不污染原始 STM）"""
    messages: List[BaseMessage]
    token_budget: int = TOKEN_BUDGET
    # 压缩状态（模块二 → 模块三）
    compressed: bool = False
    folded: bool = False
    overloaded: bool = False
    compression_note: str = ""
    # 数据库写回待办（模块执行中收集 → 流水线末尾投递队列）
    snip_queue: List[Tuple[str, str]] = field(default_factory=list)   # [(msg_id, placeholder)]
    fold_queue:  List[str]            = field(default_factory=list)   # [msg_id, ...]


# ══════════════════════════════════════════════════════════════════
# 模块一：语义级噪音过滤层 (Semantic Noise Filtration)
# ══════════════════════════════════════════════════════════════════

class SemanticNoiseFilter:
    """
    核心原则：只做物理减负，绝不破坏 AIMessage(tool_calls) ↔ ToolMessage
    的原子绑定结构（tool_call_id 完好无损）。

    Snip（精准剪枝）
        扫描距今超过 SNIP_MIN_ROUNDS_AGO 轮的旧 ToolMessage。
        若体积超过阈值，用"墓碑替换法"掏空 content，保留 tool_call_id。
        → LLM 依然能读出"我曾调用过此工具"的逻辑主线，绝不报错。

    Microcompact（微清理）
        识别连续 MICROCOMPACT_WINDOW 次相同工具+相同报错的调用链。
        将前 N-1 次失败的 ToolMessage 替换为折叠占位符，保留最后一条。

    非文本格式拦截（防御性脱水）
        Base64 图片 / 超大二进制 → 替换为 [多媒体二进制流已拦截]
        HTML 源码 → 剥离标签保留纯文本
    """

    _BASE64_RE     = re.compile(r"data:[^;]+;base64,[A-Za-z0-9+/=]{100,}")
    _HTML_TAG_RE   = re.compile(r"<[^>]{1,300}>")
    _HTML_SMELL_RE = re.compile(r"<html|<!DOCTYPE|<body|<head", re.IGNORECASE)

    SNIP_PLACEHOLDER       = "[系统回收：该工具原始数据已被 Snip 清理，核心逻辑已在后续对话中体现]"
    MICROCOMPACT_TPLTE     = "[试错过程已被 Microcompact 折叠：{err_summary}]"

    def filter(self, ctx: PipelineContext) -> PipelineContext:
        # ① 计算当前"轮次"列表（每个 HumanMessage 视为一轮开始）
        round_boundaries = [i for i, m in enumerate(ctx.messages) if isinstance(m, HumanMessage)]
        total_rounds = len(round_boundaries)

        # ② Snip：对超过 N 轮前的旧 ToolMessage 做墓碑替换
        if total_rounds > SNIP_MIN_ROUNDS_AGO:
            cutoff_idx = round_boundaries[-(SNIP_MIN_ROUNDS_AGO + 1)]
            ctx.messages, snipped = self._snip_old_tool_messages(ctx.messages, cutoff_idx)
            ctx.snip_queue.extend(snipped)

        # ③ 非文本拦截（Base64 / HTML）
        ctx.messages = [self._dehydrate(m) for m in ctx.messages]

        # ④ Microcompact：连续相同工具失败折叠
        ctx.messages, compacted = self._microcompact(ctx.messages)
        ctx.snip_queue.extend(compacted)

        return ctx

    def _snip_old_tool_messages(
        self,
        messages: List[BaseMessage],
        cutoff_idx: int,
    ) -> Tuple[List[BaseMessage], List[Tuple[str, str]]]:
        """
        对 cutoff_idx 之前的 ToolMessage 做 Snip。
        返回 (新消息列表, [(msg_id, placeholder), ...])
        """
        new_msgs = []
        snipped: List[Tuple[str, str]] = []

        for i, msg in enumerate(messages):
            if (
                i < cutoff_idx
                and isinstance(msg, ToolMessage)
                and count_str_tokens(msg.content if isinstance(msg.content, str) else "") > SNIP_TOKEN_THRESHOLD
            ):
                msg_id = getattr(msg, "id", "") or ""
                new_msg = ToolMessage(
                    content=self.SNIP_PLACEHOLDER,
                    tool_call_id=msg.tool_call_id,
                    name=getattr(msg, "name", ""),
                )
                new_msgs.append(new_msg)
                if msg_id:
                    snipped.append((msg_id, self.SNIP_PLACEHOLDER))
            else:
                new_msgs.append(msg)

        return new_msgs, snipped

    def _dehydrate(self, msg: BaseMessage) -> BaseMessage:
        """Base64 拦截 + HTML 脱水"""
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        original = content

        content = self._BASE64_RE.sub("[多媒体二进制流已拦截]", content)

        if self._HTML_SMELL_RE.search(content):
            content = self._HTML_TAG_RE.sub(" ", content)
            content = re.sub(r"\s{3,}", "\n", content).strip()

        if content == original:
            return msg
        return self._rebuild(msg, content)

    @staticmethod
    def _microcompact(
        messages: List[BaseMessage],
    ) -> Tuple[List[BaseMessage], List[Tuple[str, str]]]:
        """
        Microcompact：扫描连续 N 次相同工具+相同报错。
        将前 N-1 次失败记录替换为折叠占位符，保留最后一条完整结果。
        """
        # 收集所有 ToolMessage 的 (index, name, content_prefix)
        tool_records: List[Tuple[int, str, str]] = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                name = getattr(msg, "name", "unknown")
                prefix = (msg.content[:100] if isinstance(msg.content, str) else "")
                tool_records.append((i, name, prefix))

        if len(tool_records) < MICROCOMPACT_WINDOW:
            return messages, []

        compacted_indices: dict[int, str] = {}  # index -> placeholder

        # 滑动窗口检测
        for end in range(MICROCOMPACT_WINDOW - 1, len(tool_records)):
            window = tool_records[end - MICROCOMPACT_WINDOW + 1: end + 1]
            names    = {w[1] for w in window}
            prefixes = {w[2] for w in window}
            if len(names) == 1 and len(prefixes) == 1 and prefixes != {""}:
                # 前 N-1 条打上折叠标记，最后一条保留
                err_summary = window[0][2][:60]
                placeholder = f"[试错过程已被 Microcompact 折叠：{err_summary}]"
                for w in window[:-1]:
                    compacted_indices[w[0]] = placeholder

        if not compacted_indices:
            return messages, []

        new_msgs = []
        snipped: List[Tuple[str, str]] = []
        for i, msg in enumerate(messages):
            if i in compacted_indices:
                ph = compacted_indices[i]
                msg_id = getattr(msg, "id", "") or ""
                new_msg = ToolMessage(
                    content=ph,
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    name=getattr(msg, "name", ""),
                )
                new_msgs.append(new_msg)
                if msg_id:
                    snipped.append((msg_id, ph))
            else:
                new_msgs.append(msg)

        return new_msgs, snipped

    @staticmethod
    def _rebuild(msg: BaseMessage, content: str) -> BaseMessage:
        if isinstance(msg, ToolMessage):
            return ToolMessage(content=content, tool_call_id=msg.tool_call_id, name=getattr(msg, "name", ""))
        return msg.__class__(content=content)


# ══════════════════════════════════════════════════════════════════
# 模块二：瀑布流动态水位压缩层 (Waterfall Context Compressor)
# ══════════════════════════════════════════════════════════════════

class WaterfallCompressor:
    """
    废弃 If-Else 互斥逻辑，采用级联瀑布流，每个卡点独立判断并执行。
    切割点以 HumanMessage 为锚点，杜绝俄罗斯轮盘式的暴力截断。

    卡点 1（70%）：历史 ToolMessage 重度摘要（阈值 2000 Token，防性能倒挂）
    卡点 2（85%）：记忆折叠（从中间向上找最近 HumanMessage 作切割锚点）
    卡点 3（100%）：极端超载截断（用户上传逆天大文本的最后防线）
    """

    def __init__(self, summary_llm=None):
        self._summary_llm = summary_llm

    async def compress(self, ctx: PipelineContext) -> PipelineContext:
        warn_line   = int(ctx.token_budget * TOKEN_WARN_RATIO)
        danger_line = int(ctx.token_budget * TOKEN_DANGER_RATIO)
        fatal_line  = int(ctx.token_budget * TOKEN_FATAL_RATIO)

        # ── 第一步：精准探针称重 ───────────────────────────────
        total = count_tokens(ctx.messages)
        if total <= warn_line:
            return ctx  # 安全区，直接放行

        # ── 卡点 1（70%）：历史工具重度摘要 ──────────────────
        ctx = await self._compress_heavy_tool_messages(ctx)
        total = count_tokens(ctx.messages)

        if total <= warn_line:
            ctx.compressed = True
            ctx.compression_note = "部分旧工具返回结果已被摘要压缩。"
            return ctx

        # ── 卡点 2（85%）：绝对安全的记忆折叠 ───────────────
        if total > danger_line:
            ctx = await self._fold_memory(ctx)
            total = count_tokens(ctx.messages)
            ctx.compressed = True
            ctx.folded = True
            ctx.compression_note = (
                "注意：你的历史记忆刚刚经历过折叠，当前上下文空间紧张，"
                "请直接输出核心结论，避免冗长铺垫。"
            )

        # ── 卡点 3（100%）：极端超载截断 ─────────────────────
        if total > fatal_line:
            ctx = self._fatal_truncate(ctx)
            ctx.overloaded = True
            ctx.compression_note = (
                "系统拦截：输入内容体积过大，已强制截断早期上下文，"
                "请考虑将大文本分块处理。"
            )

        return ctx

    async def _compress_heavy_tool_messages(self, ctx: PipelineContext) -> PipelineContext:
        """
        卡点 1：对历史轮次中 Token 数 > TOOL_COMPRESS_THRESHOLD 的 ToolMessage
        调用 summary_llm 摘要，并投递 Snip 事件（写回数据库）。
        注：当前最新一轮的工具结果绝对不压缩。
        """
        # 找到最新一轮的起点（最后一个 HumanMessage 之后的内容）
        latest_human_idx = -1
        for i, m in enumerate(ctx.messages):
            if isinstance(m, HumanMessage):
                latest_human_idx = i

        new_msgs = []
        for i, msg in enumerate(ctx.messages):
            if (
                isinstance(msg, ToolMessage)
                and i < latest_human_idx           # 不碰最新一轮
                and count_str_tokens(msg.content if isinstance(msg.content, str) else "") > TOOL_COMPRESS_THRESHOLD
            ):
                summary = await self._summarize(
                    msg.content,
                    hint=f"工具 '{getattr(msg, 'name', '')}' 返回结果",
                )
                placeholder = f"[摘要] {summary}"
                msg_id = getattr(msg, "id", "") or ""
                new_msg = ToolMessage(
                    content=placeholder,
                    tool_call_id=msg.tool_call_id,
                    name=getattr(msg, "name", ""),
                )
                new_msgs.append(new_msg)
                if msg_id:
                    ctx.snip_queue.append((msg_id, placeholder))
            else:
                new_msgs.append(msg)

        ctx.messages = new_msgs
        return ctx

    async def _fold_memory(self, ctx: PipelineContext) -> PipelineContext:
        """
        卡点 2：记忆折叠。

        切割点算法（核心修复，杜绝暴力截断）：
          从消息列表的中间位置开始，向上游寻找最近的一个 HumanMessage
          作为切割锚点。切割点以下→绝对锁定区；以上→折叠区。
        """
        messages = ctx.messages

        # 分离 System 头
        sys_head  = [m for m in messages if isinstance(m, SystemMessage)]
        non_sys   = [m for m in messages if not isinstance(m, SystemMessage)]

        if len(non_sys) < 4:
            return ctx  # 消息太少，无法折叠

        # 从中间向上找最近的 HumanMessage 作锚点
        mid = len(non_sys) // 2
        anchor_idx = None
        for i in range(mid, -1, -1):
            if isinstance(non_sys[i], HumanMessage):
                anchor_idx = i
                break

        if anchor_idx is None or anchor_idx == 0:
            return ctx  # 找不到合适锚点，跳过折叠

        fold_zone = non_sys[:anchor_idx]       # 折叠区
        lock_zone = non_sys[anchor_idx:]       # 锁定区（含锚点 HumanMessage）

        # 收集折叠区的 msg_id 用于数据库写回
        fold_ids = [getattr(m, "id", "") for m in fold_zone if getattr(m, "id", "")]
        ctx.fold_queue.extend(fold_ids)

        # 浓缩折叠区
        fold_text = "\n".join(
            f"[{m.__class__.__name__}]: {(m.content if isinstance(m.content, str) else '')[:300]}"
            for m in fold_zone
        )
        summary = await self._summarize(fold_text, hint="多轮对话的早期历史")

        # 折叠摘要封装为带特殊前缀的 HumanMessage（防止 StateOrganizer 清洗 SystemMessage 时误删）
        folded_msg = HumanMessage(
            content=f"用户(系统代发)：[全局历史记忆折叠]\n{summary}"
        )

        ctx.messages = sys_head + [folded_msg] + lock_zone
        return ctx

    @staticmethod
    def _fatal_truncate(ctx: PipelineContext) -> PipelineContext:
        """
        卡点 3：极端超载截断。
        撤下过大消息，替换为强制告警。
        """
        fatal_line = int(ctx.token_budget * TOKEN_FATAL_RATIO)
        new_msgs = []
        for msg in ctx.messages:
            if count_str_tokens(msg.content if isinstance(msg.content, str) else "") > fatal_line // 2:
                new_msgs.append(
                    HumanMessage(
                        content=(
                            "[系统拦截：该文本体积过大，已被强制移除。"
                            "请使用分块阅读工具将其分步处理。]"
                        )
                    )
                )
            else:
                new_msgs.append(msg)
        ctx.messages = new_msgs
        return ctx

    async def _summarize(self, text: str, hint: str = "") -> str:
        if not self._summary_llm:
            return text[:500] + "…（已截断，未配置 summary_llm）"
        prompt = HumanMessage(
            content=f"请将以下内容压缩为简洁摘要（{hint}）：\n\n{text}"
        )
        try:
            result = await self._summary_llm.ainvoke([prompt])
            return result.content if isinstance(result.content, str) else str(result.content)
        except Exception:
            return text[:500] + "…（摘要失败，已截断）"


# ══════════════════════════════════════════════════════════════════
# 模块三：状态整理与潜意识注入层 (State Organizer)
# ══════════════════════════════════════════════════════════════════

class StateOrganizer:
    """
    核心修复点：
    1. 头部锚定 — 清理旧 SystemMessage，顶部强制注入最新 System Prompt
    2. 尾部潜意识注入 — 绝不追加新 SystemMessage！
       直接在最后一条消息（HumanMessage 或 ToolMessage）内容末尾
       拼接一段后缀，完美符合所有大模型的角色（Role）校验规范。
    """

    SUBCONSCIOUS_NOTE = (
        "\n\n[系统潜意识传输：当前上下文空间极度紧张，"
        "请立即输出核心结论或下一步动作，禁止一切冗长铺垫！]"
    )

    def organize(
        self,
        ctx: PipelineContext,
        system_prompt: str,
        env_state: dict = None,
        ltm_snippets: list = None,
    ) -> List[BaseMessage]:
        messages = ctx.messages

        # ── 头部锚定 ───────────────────────────────────────────
        # 剥除历史遗留的旧 SystemMessage（StateOrganizer 统一接管）
        messages = [m for m in messages if not isinstance(m, SystemMessage)]

        # 构建最新系统提示词（基础人设 + 环境状态 + LTM 记忆片段）
        final_system_prompt = self._build_system_prompt(
            base_prompt=system_prompt,
            env_state=env_state or {},
            ltm_snippets=ltm_snippets or [],
        )

        if final_system_prompt:
            messages = [SystemMessage(content=final_system_prompt)] + messages

        # ── 尾部潜意识注入 ─────────────────────────────────────
        # 只在发生过压缩/折叠/超载时才注入（不要无端污染正常对话）
        if ctx.compression_note and messages:
            last = messages[-1]
            last_content = last.content if isinstance(last.content, str) else str(last.content)
            # 只向 HumanMessage 或 ToolMessage 尾部追加（保持角色合法）
            if isinstance(last, (HumanMessage, ToolMessage)):
                new_last = SemanticNoiseFilter._rebuild(
                    last,
                    last_content + self.SUBCONSCIOUS_NOTE,
                )
                messages[-1] = new_last

        return messages

    @staticmethod
    def _build_system_prompt(
        base_prompt: str,
        env_state: dict,
        ltm_snippets: list,
    ) -> str:
        """
        将基础人设、当前环境状态、LTM 记忆片段组装成完整系统提示词。
        环境状态始终注入（时间感知）；LTM 片段只在有内容时追加。
        """
        parts = []

        if base_prompt:
            parts.append(base_prompt)

        # 注入当前精确时间和星期
        if env_state:
            time_str = env_state.get("current_time", "")
            weekday  = env_state.get("weekday", "")
            if time_str:
                env_block = f"【当前系统时间】{time_str}"
                if weekday:
                    env_block += f"（{weekday}）"
                parts.append(env_block)

        # 注入长期记忆片段（历史画像 / 偏好 / 事实）
        if ltm_snippets:
            ltm_lines = "\n".join(f"- {s}" for s in ltm_snippets if s)
            if ltm_lines:
                parts.append(f"【用户长期记忆（历史画像与偏好）】\n{ltm_lines}")

        return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════════
# 总调度器：唯一对外接口
# ══════════════════════════════════════════════════════════════════

class ContextPipeline:
    """
    预处理总调度器。
    AgentLoop while 循环第一步只调用 prepare()，内部像无人工厂流水线：
      先筛废料（过滤） → 再打包压实（压缩） → 最后贴发货标签（整理状态）
    最终输出绝对安全的消息列表直接喂给推理引擎。

    数据库持久化采用"只读快照 + 异步事件写回"策略：
      内存清洗完成后，将 SnipEvent/FoldEvent 批量投递到
      core.db_write_queue，由后台 Worker 异步落库，零阻塞。
    """

    def __init__(
        self,
        system_prompt: str = "",
        summary_llm=None,
        token_budget: int = TOKEN_BUDGET,
    ):
        self._system_prompt = system_prompt
        self._filter     = SemanticNoiseFilter()
        self._compressor = WaterfallCompressor(summary_llm=summary_llm)
        self._organizer  = StateOrganizer()
        self._token_budget = token_budget

    async def prepare(
        self,
        stm,
        env_state: dict = None,
        ltm_snippets: list = None,
    ) -> List[BaseMessage]:
        """
        流水线主入口。
        接受 ShortTermMemory 对象（非快照），内部：
          ① [Harness] context_optimizer: 超长文档目录化（Snip 之前的物理截断）
          ② 读取当前 STM 消息快照进行清洗（不污染源数据）
          ③ 将清洗后的消息写回 STM（防止下轮数据库加载时垃圾数据复活）
          ④ 返回最终注入了 System Prompt / 环境状态 / LTM 的消息列表
        """
        raw_messages = stm.get_messages() if hasattr(stm, "get_messages") else list(stm)

        # ── [Harness] Step 0: context_optimizer — 超长文档目录化 ──────
        # 扫描新注入的消息；若某条消息内容超过 100 行，
        # 将其替换为 Markdown 摘要目录，原文存入 optimizer 内部缓存，
        # 模型后续可通过 fetch_section 按需拉取具体段落。
        optimizer = self._get_context_optimizer()
        if optimizer:
            processed = []
            for i, msg in enumerate(raw_messages):
                content = msg.content if isinstance(msg.content, str) else ""
                if content and content.count("\n") >= 100:
                    doc_id = f"msg_{id(msg)}_{i}"
                    compressed = optimizer.compress_to_directory(content, doc_id=doc_id)
                    if compressed != content:
                        if isinstance(msg, ToolMessage):
                            msg = ToolMessage(
                                content=compressed,
                                tool_call_id=msg.tool_call_id,
                                name=getattr(msg, "name", ""),
                            )
                        else:
                            msg = msg.__class__(content=compressed)
                processed.append(msg)
            raw_messages = processed

        ctx = PipelineContext(
            messages=list(raw_messages),
            token_budget=self._token_budget,
        )

        # ① 语义级噪音过滤
        ctx = self._filter.filter(ctx)

        # ② 瀑布流动态水位压缩（可能调用 summary_llm）
        ctx = await self._compressor.compress(ctx)

        # ③ 将清洗后的裸消息写回 STM（过滤掉 SystemMessage，只保留对话体）
        #    目的：防止下一轮从 DB 加载时已被 Snip/Fold 的旧内容死灰复燃
        if hasattr(stm, "messages"):
            stm.messages = [m for m in ctx.messages if not isinstance(m, SystemMessage)]

        # ④ 状态整理与潜意识注入（注入 System Prompt + 环境状态 + LTM）
        final_messages = self._organizer.organize(
            ctx,
            system_prompt=self._system_prompt,
            env_state=env_state or {},
            ltm_snippets=ltm_snippets or [],
        )

        # ⑤ 异步投递数据库写回事件（非阻塞，零延迟）
        self._flush_db_events(ctx)

        return final_messages

    @staticmethod
    def _get_context_optimizer():
        """通过 middleware_plugin_hub 取 context_optimizer 插件实例，未激活返回 None。"""
        try:
            from harness_framework.middleware_plugin_hub import get_active_plugin
            return get_active_plugin("context_optimizer")
        except Exception:
            return None

    @staticmethod
    def _flush_db_events(ctx: PipelineContext) -> None:
        """
        将本轮流水线收集的 Snip/Fold 事件批量投递到写回队列。
        put_nowait 是同步操作，不阻塞 AgentLoop。
        """
        try:
            from core.db_write_queue import emit_snip, emit_fold
            for msg_id, placeholder in ctx.snip_queue:
                emit_snip(msg_id, placeholder)
            if ctx.fold_queue:
                emit_fold(ctx.fold_queue)
        except Exception:
            pass  # 写回失败不影响内存状态，仅丧失持久化，可接受
