# VibeTrace

[English](README.md) | [中文](README.zh-CN.md)

> Turn agent debugging from guessing into watching and AI-explained.

An observability, debugging, and reliability toolkit for AI agents. Built for the
hardest problems of the vibe-coding era: observability, reliability, and vibe
deviation detection.

## Components

| Component | Description | Stack |
|----------|-------------|-------|
| **[vibetrace (Python)](vibetrace/)** | Core library: tracer, storage, analyst | Python 3.10+, zero core deps |
| **[vibetrace-desktop](vibetrace-desktop/)** | Desktop app with one-click Claude Code integration | Tauri + Rust + React |
| **vibetrace (CLI)** | Command-line tool shipped with the Python package | argparse |
| **vibetrace dashboard** | Web dashboard shipped with the Python package | Streamlit |

## Features

- **One-line instrumentation** - `@trace_agent()`, `with trace(...):`, or automatic Claude Code hooks
- **Full traces** - LLM calls, tool calls, reasoning, memory, errors, retries, and cost
- **AI Analyst** - root cause analysis, pattern detection, and suggestions (LLM plus rule-based)
- **Vibe Check** - detect when output drifts from the intended vibe (calm, minimalist, professional, etc.)
- **Loop Detection** - surface infinite loops and repeated reasoning automatically
- **Cost and reliability guards** - token and cost accounting with threshold alerts
- **Local-first** - all data stays in a local SQLite database, no cloud dependency
- **Multiple surfaces** - web (Streamlit), desktop (Tauri), CLI

## Quick start

### Option A: Desktop app (recommended, auto-monitors Claude Code)

1. Download the [latest release](https://github.com/sakurairo/VibeTrace/releases)
2. Launch VibeTrace
3. Click "Setup Claude Code Hooks" in the sidebar
4. Use Claude Code as usual - every prompt and tool call is recorded

### Option B: Python library

The core library has zero dependencies (pure standard library), so instrumentation
adds nothing to your dependency tree.

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

### Option C: CLI

```bash
vibetrace demo           # run the demo agent
vibetrace dashboard      # launch the web dashboard
vibetrace list           # list recent traces
vibetrace show <id>      # show trace details
vibetrace stats          # show global statistics
vibetrace analyze <id>   # run the analyst on a trace
vibetrace clean          # delete all traces
```

## Architecture

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

- **Python core**: tracer (contextvars), SQLite storage, analyst (LLM plus rules)
- **Desktop backend**: Rust, Tauri 2, axum (HTTP), rusqlite (bundled SQLite)
- **Desktop frontend**: React, TypeScript, Vite
- **Dashboard**: Streamlit

## Claude Code integration

The desktop app connects to Claude Code through this flow:

1. **HTTP server starts** on port 7842
   - `POST /v1/traces` - create a trace
   - `POST /v1/events` - record an event
   - `POST /v1/events/finish` - finish an event
   - `POST /v1/traces/end` - end a trace

2. **Hooks are written** to `~/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "curl -X POST ..."}]}],
       "PostToolUse": [{"hooks": [{"type": "command", "command": "curl -X POST ..."}]}],
       "Stop": [{"hooks": [{"type": "command", "command": "curl -X POST ..."}]}]
     }
   }
   ```

3. **When you send a prompt** to Claude Code, the hook fires and the HTTP server
   records the trace start. **Each tool call** records an event. **On stop**, the
   trace is marked complete.

4. **The desktop app** polls the local SQLite database every 3 seconds and shows
   new traces in real time.

## Optional dependencies

The core library installs nothing extra. Add what you need:

```bash
pip install "vibetrace[dashboard]"   # Streamlit web dashboard
pip install "vibetrace[anthropic]"   # Anthropic SDK auto-tracing
pip install "vibetrace[openai]"      # OpenAI SDK auto-tracing
pip install "vibetrace[all]"         # everything above
```

## Roadmap

- [x] Python core library plus Streamlit dashboard
- [x] Tauri desktop app plus Claude Code integration
- [x] AI Analyst (LLM plus rule-based)
- [x] Vibe Check panel
- [x] Loop Detection
- [ ] Vector memory (similar-trace retrieval)
- [ ] Replay UI (edit a prompt and re-run a subtree)
- [ ] LangGraph and OpenAI auto-hooks
- [ ] PDF report export
- [ ] Web version (Vercel deployment)

## Development

### Python package

```bash
pip install -e ".[all]"
python tests/test_tracer.py   # 8 tests
vibetrace dashboard
```

### Desktop app

```bash
cd vibetrace-desktop
npm install
npm run tauri dev
```

## Release process

1. Bump the version in `vibetrace-desktop/src-tauri/Cargo.toml` and `vibetrace-desktop/package.json`
2. `git tag v0.1.0 && git push --tags`
3. GitHub Actions cross-compiles for all platforms and publishes artifacts to the `Latest` release

## License

MIT (c) VibeTrace Contributors

---

*Built with vibe coding - calm, insightful, minimalist.*
