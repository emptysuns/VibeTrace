# VibeTrace

[English](README.md) | [中文](README.zh-CN.md)

> 让 Agent 调试从"猜"变成"看 + AI 解释"。

一套针对 AI Agent 的可观测性、调试与可靠性工具。专为 vibe coding 时代最顽固的痛点而构建:
可观测性、可靠性, 以及 Vibe 偏离检测。

## 包含的组件

| 组件 | 描述 | 技术栈 |
|------|------|--------|
| **[vibetrace (Python)](vibetrace/)** | 核心库: tracer, storage, analyst | Python 3.10+, 核心零依赖 |
| **[vibetrace-desktop](vibetrace-desktop/)** | 桌面应用, 一键接入 Claude Code | Tauri + Rust + React |
| **vibetrace (CLI)** | 命令行工具 (随 Python 包附带) | argparse |
| **vibetrace dashboard** | Web dashboard (随 Python 包附带) | Streamlit |

## 核心特性

- **一行接入** - `@trace_agent()`、`with trace(...):`, 或自动 Claude Code hooks
- **完整轨迹** - LLM calls, tool calls, reasoning, memory, errors, retries, cost
- **AI Analyst** - 根因分析、模式检测、改进建议 (LLM + rule-based 双引擎)
- **Vibe Check** - 检测输出是否偏离原始 vibe (calm, minimalist, professional 等)
- **Loop Detection** - 自动发现无限循环与重复 reasoning
- **Cost 与可靠性护栏** - token 与 cost 统计, 超阈值预警
- **Local-first** - 全部数据存于本地 SQLite, 无云依赖
- **多端** - Web (Streamlit)、Desktop (Tauri)、CLI

## 快速开始

### 方式 A: 桌面应用 (推荐, 自动监控 Claude Code)

1. 下载 [最新 release](https://github.com/sakurairo/VibeTrace/releases)
2. 启动 VibeTrace
3. 点击侧栏 "Setup Claude Code Hooks"
4. 像平时一样用 Claude Code - 所有 prompt 与 tool call 都会被记录

### 方式 B: Python 库

核心库零依赖 (纯标准库实现), 因此接入不会给你的依赖树增加任何负担。

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
vibetrace list           # 列出最近 traces
vibetrace show <id>      # 查看 trace 详情
vibetrace stats          # 查看全局统计
vibetrace analyze <id>   # 对单个 trace 运行 analyst
vibetrace clean          # 删除所有 traces
```

## 架构

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

- **Python 核心**: tracer (contextvars)、SQLite 存储、analyst (LLM + rules)
- **桌面后端**: Rust、Tauri 2、axum (HTTP)、rusqlite (bundled SQLite)
- **桌面前端**: React、TypeScript、Vite
- **Dashboard**: Streamlit

## Claude Code 集成细节

桌面应用通过以下流程接入 Claude Code:

1. **HTTP Server 启动** (port 7842)
   - `POST /v1/traces` - 创建 trace
   - `POST /v1/events` - 记录 event
   - `POST /v1/events/finish` - 结束 event
   - `POST /v1/traces/end` - 结束 trace

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

3. **每次你发送 prompt 给 Claude Code**, hook 会触发, HTTP server 记录 trace 开始。**每个 tool 调用** 都会记录 event。**stop 时** 标记 trace 结束。

4. **桌面应用** 每 3 秒轮询本地 SQLite, 实时显示新 trace。

## 可选依赖

核心库默认不安装任何额外依赖。按需安装:

```bash
pip install "vibetrace[dashboard]"   # Streamlit Web dashboard
pip install "vibetrace[anthropic]"   # Anthropic SDK 自动追踪
pip install "vibetrace[openai]"      # OpenAI SDK 自动追踪
pip install "vibetrace[all]"         # 以上全部
```

## 路线图

- [x] Python 核心库 + Streamlit dashboard
- [x] Tauri 桌面应用 + Claude Code 集成
- [x] AI Analyst (LLM + rule-based)
- [x] Vibe Check 面板
- [x] Loop Detection
- [ ] Vector memory (相似 trace 检索)
- [ ] Replay UI (修改 prompt 重跑子树)
- [ ] LangGraph 与 OpenAI 自动 hook
- [ ] PDF 报告导出
- [ ] Web 版本 (Vercel 部署)

## 开发

### Python 包

```bash
pip install -e ".[all]"
python tests/test_tracer.py   # 8 个测试
vibetrace dashboard
```

### 桌面应用

```bash
cd vibetrace-desktop
npm install
npm run tauri dev
```

## 发布流程

1. 改 `vibetrace-desktop/src-tauri/Cargo.toml` 和 `vibetrace-desktop/package.json` 中的 version
2. `git tag v0.1.0 && git push --tags`
3. GitHub Actions 自动 cross-platform 编译, 全部产物发布到 `Latest` release

## License

MIT (c) VibeTrace Contributors

---

*Built with vibe coding - calm, insightful, minimalist.*
