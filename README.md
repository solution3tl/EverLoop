<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=32&duration=3000&pause=1000&color=6366F1&center=true&vCenter=true&width=600&lines=🌀+EverLoop;Autonomous+Agent+Framework" alt="EverLoop" />

**A production-grade autonomous agent framework with layered memory,**
**MCP ecosystem, and zero-intrusion harness architecture.**

<br/>

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![LangChain](https://img.shields.io/badge/LangChain-latest-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain.com)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)

<br/>

> *A loop that never breaks, never bloats, and never forgets what matters.*

</div>

---

## 🤔 What is EverLoop?

本项目是对 3 月 31 日 Claude Code 源码泄露事件的技术演进。我们在第一时间剥离并复现了其底层极其优秀的自主 Agent 运转机制，并在此基础上重新设计、抽象出了一套完整的工程化框架。

EverLoop 的核心建立在一个严密的 7 步 `while` 循环范式之上。每一次对话轮次都会精准调度以下核心模块：
* **上下文工程 (Context Engineering)：** 内置 4 级瀑布式压缩与语义降噪，确保极高频的工具输出绝不污染 Token 池。
* **分层记忆管理 (Layered Memory)：** 将线程级的短期记忆 (STM) 与基于向量检索的长期记忆 (LTM) 无缝解耦。
* **可靠工具调用 (Tool Calling & MCP)：** 支持标准化外部工具接入与沙盒执行。
* **Harness 插件体系：** 以**对核心逻辑零侵入**的方式挂载各类守卫（Guard）、拦截器（Linter）与清理守护进程。


---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        AgentLoop.arun()                      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    while True:                       │   │
│  │                                                     │   │
│  │  Step 0  [Harness] isolation_guard / context_opt.  │   │
│  │  Step 1  ContextPipeline.prepare()                 │   │
│  │           ├─ LTM RAG retrieval                     │   │
│  │           ├─ SemanticNoiseFilter (Snip + Compact)  │   │
│  │           ├─ WaterfallCompressor (4-stage)         │   │
│  │           └─ StateOrganizer (anchor + inject)      │   │
│  │  Step 2  Precondition check + plugin health gate   │   │
│  │  Step 3  LLM inference (true streaming via astream)│   │
│  │          [Harness] sandwich_reasoning on demand    │   │
│  │  Step 4  Result check + [Harness] deterministic_   │   │
│  │          linter hard validation                    │   │
│  │  Step 5  Tool execution → STM write-back           │   │
│  │          [Harness] wrap_child_agent summarization  │   │
│  │  Step 6  Termination check                         │   │
│  │  Step 7  Next iteration                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Post-loop: LTM session summarization & persistence        │
└─────────────────────────────────────────────────────────────┘
```

---

## ✨ Core Features

### 🔗 Harness Plugin Framework
A middleware architecture that attaches capabilities to the agent loop without modifying any core code. Plugins are registered in `middleware_plugin_hub`, health-checked on every iteration, and auto-disabled when fault rate exceeds threshold.

| Plugin | Role |
|--------|------|
| `sandwich_reasoning` | Routes complex tasks through plan → execute → verify pipeline using different LLMs |
| `deterministic_linter` | Hard-validates LLM output, auto-rejects and re-prompts on failure |
| `isolation_guard` | Cuts parent context when spawning child agents, preventing cognitive contamination |
| `context_optimizer` | Compresses mailbox history in long-running sub-agent calls |
| `janitor_daemon` | Background async cleanup of expired sessions and orphaned tool results |

### 🧠 Layered Memory System

**🟣 Short-Term Memory (STM)**
- Per-thread in-memory conversation store
- Auto-summarizes when approaching context limits
- Write-through to async DB queue (never blocks the loop)

**🔵 Long-Term Memory (LTM)**
- Extracts user facts and preferences from each session
- Vector-store backed semantic retrieval (BGE / Milvus extensible)
- Injected at Step 1 of every new conversation as grounding context

---

### 📦 Context Pipeline — 4-Stage Waterfall Compressor

The pipeline is the core defense against context bloat. Even if a tool writes 100k characters of logs, the next loop iteration cleans it down before it reaches the LLM.

```
  Raw STM messages
        │
        ▼
  ┌─────────────────────────────────┐
  │       SemanticNoiseFilter       │
  │  ├─ Snip: prune old tool output │
  │  └─ Microcompact: fold errors   │
  └─────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────┐
  │   WaterfallCompressor (×4)      │
  │   progressive token reduction   │
  │   results written back to STM   │
  └─────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────┐
  │        StateOrganizer           │
  │  ├─ Head: system prompt anchor  │
  │  └─ Tail: LTM + env injection   │
  └─────────────────────────────────┘
        │
        ▼
  messages_for_llm  ──►  LLM
```

---

### 🔌 MCP Ecosystem

Full [Model Context Protocol](https://modelcontextprotocol.io) support. External tool servers are registered through `ServerManager`, which handles lifecycle, permission isolation, endpoint validation, and health monitoring. Agents gain unlimited tool surface area without touching core code.

### 🛠️ Skill System

Skills are self-contained capability packages with their own virtual filesystem. An agent can browse skill files (`list_skill_files`), read them, and execute skill-specific tools — all within an isolated workspace. Ideal for packaging domain-specific workflows (code review, document generation, data analysis pipelines).

---

### 🌊 True Streaming with Typed Packet Protocol

Every SSE event carries a typed packet. The frontend routes each packet type to the correct renderer — no raw JSON leaks to the user.

| Packet Type | Frontend Behavior |
|:-----------:|-------------------|
| `think` | 💭 Streams into collapsible thinking block with breathing indicator |
| `think_end` | ✦ Auto-collapses thinking block, shows *"已深度思考"* |
| `text` | ⌨️ Typewriter effect in main answer bubble |
| `text_replace` | 🔄 Atomically replaces streamed text (used after inline tool-call cleanup) |
| `tool_call_start` | 🔵 Shows tool card with breathing-light animation |
| `tool_call_done` | ✅ Updates card to ✓ done, previews result |
| `control` | 🎛️ Stream lifecycle (start / done / error) |

---

## 📁 Project Structure

```
EverLoop/
├── 🚀 main.py                      # Entry point (FastAPI on :8001)
├── 📡 api/
│   ├── router.py                   # Route registration
│   ├── chat_endpoint.py            # SSE streaming endpoint
│   ├── auth_endpoint.py            # JWT auth
│   ├── mcp_endpoint.py             # MCP server management API
│   └── skill_endpoint.py           # Skill invocation API
├── ⚙️  core/
│   ├── agent_loop.py               # The 7-step while loop
│   ├── context_pipeline.py         # Waterfall context compressor
│   ├── streaming_handler.py        # SSE packet builder & dispatcher
│   └── react_agent.py              # ReAct agent implementation
├── 🧠 memory/
│   ├── short_term_memory.py        # Thread-scoped STM with auto-summarize
│   ├── long_term_memory.py         # Fact extraction + vector retrieval
│   └── memory_manager.py           # Unified memory facade
├── 🔩 harness_framework/
│   ├── middleware_plugin_hub.py    # Plugin registry + health gate
│   ├── sandwich_reasoning.py       # Plan→Execute→Verify harness
│   ├── deterministic_linter.py     # Output validation harness
│   ├── isolation_guard.py          # Child agent context isolation
│   ├── context_optimizer.py        # Mailbox compression harness
│   └── janitor_daemon.py           # Background cleanup daemon
├── 🔌 mcp_ecosystem/
│   ├── server_manager.py           # MCP server lifecycle
│   ├── pipeline_manager.py         # Tool pipeline orchestration
│   └── mcp_agent.py                # MCP-aware agent wrapper
├── 🛠️  skill_system/
│   ├── initializer.py              # Virtual FS + tool generation
│   └── main_skill_agent.py         # Skill execution agent
├── 📞 function_calling/
│   ├── tool_registry.py            # Tool registration & schema
│   └── builtin_tools.py            # Built-in tool implementations
├── 🤝 multi_agent/
│   ├── swarm_router.py             # Swarm-style agent routing
│   └── team_network.py             # Team network topology
├── 🤖 llm/
│   ├── llm_factory.py              # Multi-provider LLM factory
│   └── model_config.py             # Model configuration
├── 🗄️  database/
│   ├── models.py                   # SQLAlchemy models
│   ├── crud.py                     # Async CRUD operations
│   ├── vector_store.py             # Vector DB abstraction
│   └── session_store.py            # Session persistence
└── 🖥️  frontend/
    └── src/
        ├── App.tsx                 # Root app with model selector
        ├── components/
        │   ├── ChatWindow.tsx      # Message list + scroll management
        │   ├── MessageBubble.tsx   # Think block + tool cards + Markdown
        │   ├── InputBox.tsx        # Input with send controls
        │   └── ActionStatusBar.tsx # Global status display
        └── store/
            └── chatStore.ts        # Zustand state (messages, models, SSE)
```

---

## 🚀 Quick Start

### Prerequisites

- ![Python](https://img.shields.io/badge/-Python_3.10+-3776AB?style=flat&logo=python&logoColor=white) 
- ![Node](https://img.shields.io/badge/-Node.js_18+-339933?style=flat&logo=node.js&logoColor=white)
- An LLM API key (OpenAI-compatible endpoint)

### 1️⃣ Backend

```bash
cd EverLoop
pip install -r requirements.txt

# Configure your LLM endpoint
cp .env.example .env
# Edit .env: set API_KEY, BASE_URL, MODEL_NAME

python main.py
# ✅ Server starts on http://127.0.0.1:8001
```

### 2️⃣ Frontend

```bash
cd EverLoop/frontend
npm install
npm run dev
# ✅ UI available on http://localhost:5173
```

---

## ⚙️ Configuration

| Variable | Description |
|----------|-------------|
| `LLM_API_KEY` | API key for your LLM provider |
| `LLM_BASE_URL` | OpenAI-compatible base URL |
| `LLM_MODEL_NAME` | Model identifier |
| `DATABASE_URL` | SQLite / PostgreSQL connection string |
| `JWT_SECRET` | Secret for JWT token signing |
| `VECTOR_STORE_PATH` | Path for local vector store persistence |

---

## 💡 Design Philosophy

<table>
<tr>
<td align="center" width="25%">
<h3>🔁</h3>
<strong>The loop is sacred</strong><br/>
<sub>Every optimization exists to keep the while loop running cleanly without compromising the core reasoning path.</sub>
</td>
<td align="center" width="25%">
<h3>🧩</h3>
<strong>Plugins are guests</strong><br/>
<sub>Any plugin failure degrades gracefully to baseline behavior. A broken harness means ordinary inference, not a 500 error.</sub>
</td>
<td align="center" width="25%">
<h3>🪣</h3>
<strong>Context is a resource</strong><br/>
<sub>Token budget is treated like memory bandwidth — aggressively reclaimed, never wasted, deterministically compressed.</sub>
</td>
<td align="center" width="25%">
<h3>📡</h3>
<strong>Streaming is a contract</strong><br/>
<sub>The typed SSE packet protocol is the hard boundary between backend intelligence and frontend rendering.</sub>
</td>
</tr>
</table>

---

## 🧰 Tech Stack

<div align="center">

**Backend**

![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=flat&logo=langchain&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat&logo=sqlalchemy&logoColor=white)
![JWT](https://img.shields.io/badge/JWT-000000?style=flat&logo=jsonwebtokens&logoColor=white)

**Frontend**

![React](https://img.shields.io/badge/React_18-61DAFB?style=flat&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat&logo=vite&logoColor=white)
![Zustand](https://img.shields.io/badge/Zustand-443E38?style=flat)

**AI / ML**

![OpenAI](https://img.shields.io/badge/OpenAI_Compatible-412991?style=flat&logo=openai&logoColor=white)
![Vector DB](https://img.shields.io/badge/Vector_Store-BGE_/_Milvus-FF6B6B?style=flat)

</div>

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">
<br/>
<img src="https://img.shields.io/badge/Built_with-obsessive_attention_to_context_engineering-6366f1?style=for-the-badge" />
<br/><br/>
<sub>If EverLoop helps you ship smarter agents, consider giving it a ⭐</sub>
</div>
