# VibeTrace 🪄🔍

> **让 Agent 调试从"猜"变成"看 + AI 解释"**
>
> 一套针对 AI Agent 的可观测性、调试与可靠性工具。
> 直接针对 vibe coding 时代最顽固的痛点：**Observability + Reliability + Vibe 偏离检测**。

## 🧩 包含的组件

| 组件 | 描述 | 技术栈 |
|------|------|--------|
| **[vibetrace (Python)](vibetrace/)** | 核心 Python 库: tracer, storage, analyst | Python 3.10+ |
| **[vibetrace-desktop](vibetrace-desktop/)** | 桌面应用 + Claude Code 自动集成 | Tauri + Rust + React |
| **vibetrace (CLI)** | 命令行工具 (Python 包附带) | Click |
| **vibetrace dashboard** | Web dashboard (Python 包附带, Streamlit) | Streamlit |

## 📸 截图 (vibetrace-desktop)

> 桌面应用提供时间线、Graph 视图、AI 分析师和 Vibe Check 面板,
> 一键接入 Claude Code hooks, 自动捕获所有 agent 行为。

## ✨ 核心特性

- 🪄 **一行接入** — `@trace_agent()` / `with trace(...):` / 自动 Claude Code hooks
- 🌳 **完整轨迹** — LLM calls, tool calls, reasoning, memory, errors, retries, cost
- 🧠 **AI Analyst** — 根因分析、模式检测、改进建议 (LLM + rule-based 双引擎)
- 🎨 **Vibe Check** — 检测输出是否偏离原始 vibe (calm, minimalist, professional 等)
- 🔁 **Loop Detection** — 自动发现无限循环 / 重复 reasoning
- 🛡️ **Cost & Reliability Guards** — token / cost 统计、超阈值预警
- 💾 **Local-first** — 全部数据存本地 SQLite, 无云依赖
- 🖥️ **多端** — Web (Streamlit), Desktop (Tauri), CLI

## 🚀 快速开始

### 方式 A: 桌面应用 (推荐, 自动监控 Claude Code)

1. 下载 [最新 release](https://github.com/sakurairo/VibeTrace/releases)
2. 启动 VibeTrace
3. 点击侧栏 "⚡ Setup Claude Code Hooks"
4. 像平时一样用 Claude Code —— 所有 prompt / tool call 都会被记录

### 方式 B: Python 库

```bash
pip install vibetrace
```

```python
from vibetrace import trace, event, trace_agent
from vibetrace.core.events import EventType

@trace_agent(name="my-coder", vibe="minimalist and calm")
def my_agent(task: str) -> str:
    plan = llm_call(f"Plan: {task}")
    return plan

my_agent("Build a website")
```

### 方式 C: CLI

```bash
vibetrace demo           # 运行 demo agent
vibetrace dashboard      # 启动 Web dashboard
vibetrace list           # 列出 traces
vibetrace show <id>      # 查看 trace 详情
vibetrace analyze <id>   # AI 分析
```

## 🏗️ 架构

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Claude Code  │    │  Custom      │    │  LangGraph   │
│ (hooks)      │    │  Agent       │    │  / CrewAI    │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       │  HTTP             │  Python           │  Python
       ▼                   ▼                   ▼
┌────────────────────────────────────────────────────┐
│              VibeTrace Core                        │
│  ┌────────────┐  ┌──────────┐  ┌────────────┐    │
│  │ Tracer     │  │ Storage  │  │ Analyst    │    │
│  │ (contextvars)│  │(SQLite) │  │ (LLM+rules)│    │
│  └────────────┘  └──────────┘  └────────────┘    │
└────────────────────────┬───────────────────────────┘
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       ┌─────────────┐      ┌─────────────┐
       │  Streamlit  │      │  Tauri      │
       │  Dashboard  │      │  Desktop    │
       └─────────────┘      └─────────────┘
```

## 🤖 Claude Code 集成细节

桌面应用通过以下流程接入 Claude Code:

1. **HTTP Server 启动** (port 7842)
   - `POST /v1/traces` — 创建 trace
   - `POST /v1/events` — 记录 event
   - `POST /v1/traces/end` — 结束 trace

2. **Hook 写入** `~/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "curl -X POST ..."}]}],
       "PostToolUse": [{"hooks": [{"type": "command", "command": "curl -X POST ..."}]}],
       "Stop": [{"hooks": [{"type": "command", "command": "curl -X POST ..."}]}]
     }
   }
   ```

3. **每次你发送 prompt 给 Claude Code**, 它会自动调用 hook, 我们的 HTTP server 记录 trace 开始; **每个 tool 调用** 都会记录 event; **stop 时** 标记 trace 结束。

4. **桌面应用** 每 3 秒轮询本地 SQLite, 实时显示新 trace。

## 🗺️ 路线图

- [x] Python 核心库 + Streamlit dashboard
- [x] Tauri 桌面应用 + Claude Code 集成
- [x] AI Analyst (LLM + rule-based)
- [x] Vibe Check 面板
- [x] Loop Detection
- [ ] Vector memory (相似 trace 检索)
- [ ] Replay UI (修改 prompt 重跑子树)
- [ ] LangGraph / OpenAI 自动 hook
- [ ] Export PDF 报告
- [ ] Web 版本 (Vercel 部署)

## 🛠️ 开发

### Python 包

```bash
pip install -e ".[all]"
python tests/test_tracer.py  # 8 tests
vibetrace dashboard
```

### 桌面应用

```bash
cd vibetrace-desktop
npm install
npm run tauri dev
```

## 📦 发布流程

1. 改 `vibetrace-desktop/src-tauri/Cargo.toml` 和 `vibetrace-desktop/package.json` 中的 version
2. `git tag v0.1.0 && git push --tags`
3. GitHub Actions 自动 cross-platform build, 全部产物发布到 `Latest` release

## 🪪 License

MIT © VibeTrace Contributors

---

*Built with vibe coding — calm, insightful, minimalist.*
