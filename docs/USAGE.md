# VibeTrace 使用指南 🪄🔍

## 三种使用方式

### 1️⃣ 桌面应用 (自动监控 Claude Code)

**这是最推荐的方式** — 零配置，自动捕获你所有的 Claude Code 工作流。

```bash
# 1. 下载并启动 VibeTrace.app / .exe / .AppImage
# 2. 启动后, 它自动:
#    - 监听 http://127.0.0.1:7842 (HTTP API)
#    - 把数据存到 ~/Library/Application Support/dev.vibetrace.app/vibetrace.db
# 3. 点击侧栏 "⚡ Setup Claude Code Hooks"
#    - 自动修改 ~/.claude/settings.json
#    - 配置 UserPromptSubmit / PostToolUse / Stop 三个 hook
# 4. 像平时一样用 Claude Code
# 5. 回到 VibeTrace 桌面应用看 traces (每 3 秒自动刷新)
```

### 2️⃣ Python 库 (自定义 agent)

```bash
pip install vibetrace
```

```python
from vibetrace import trace, event, trace_agent
from vibetrace.core.events import EventType

# 方式 A: 装饰器
@trace_agent(name="research-agent", vibe="thoughtful and thorough")
def my_research_agent(query: str) -> str:
    return "..."

# 方式 B: context manager (更细粒度)
with trace("my-agent", vibe="minimalist") as t:
    t.set_input(query)

    with event("plan", EventType.REASONING) as e:
        e.set_input(...)
        e.set_output(...)

    with event("call-llm", EventType.LLM_CALL, model="claude-opus-4-8") as e:
        e.set_input(prompt)
        response = call_llm(...)
        e.set_output(response, total_tokens=1234, cost_usd=0.045)

    t.set_output(final_answer)
```

然后跑 dashboard 看：
```bash
vibetrace dashboard
# 打开 http://localhost:8501
```

### 3️⃣ 自动集成 (LangGraph / OpenAI / Anthropic)

```python
# 拦截 Anthropic SDK
from vibetrace.integrations.anthropic import patch
patch()

# 之后所有 anthropic.Anthropic().messages.create() 自动追踪
```

## 常见场景

### 🔍 场景 1: 调试失败的 Claude Code 任务

1. 运行 VibeTrace 桌面应用
2. Setup Claude Code Hooks
3. 在 Claude Code 跑一个会失败的任务
4. 回到 VibeTrace, 看到失败 trace (❌)
5. 点 "🧠 Analyst" tab → 看根因分析
6. 点 "🎨 Vibe" tab → 检查 vibe 偏离

### 💰 场景 2: 监控 token / cost

1. 用 Python 库 + `@trace_agent` 装饰你的 agent
2. 跑 `vibetrace stats` → 看总 cost / token
3. 在 dashboard 看哪个 trace / event 花钱最多

### 🔁 场景 3: 检测无限循环

VibeTrace 自动检测 reasoning 重复 ≥3 次, 标记 `loop_detected` 事件。

### 🎨 场景 4: Vibe Check (meta-debugging)

```python
with trace("ui-gen", vibe="calm, minimalist, generous whitespace"):
    # ... agent 可能输出了"loud"内容
    pass
# Analyst 自动对比 vibe vs 实际输出
```

## Claude Code Hooks 详解

`~/.claude/settings.json` 被修改后包含:

```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "curl -s -X POST http://127.0.0.1:7842/v1/traces -H 'Content-Type: application/json' -d '{\"name\":\"claude-code\",\"vibe\":\"calm and insightful\",\"input\":{\"prompt\":\"$PROMPT\"}}'"
      }]
    }],
    "PostToolUse": [{
      "hooks": [{
        "type": "command",
        "command": "curl -s -X POST http://127.0.0.1:7842/v1/events -H 'Content-Type: application/json' -d '{\"name\":\"$TOOL\",\"event_type\":\"tool.call\",\"tool_name\":\"$TOOL\",\"metadata\":{}}'"
      }]
    }],
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "curl -s -X POST http://127.0.0.1:7842/v1/traces/end -H 'Content-Type: application/json' -d '{\"trace_id\":\"$TRACE_ID\"}'"
      }]
    }]
  }
}
```

如果你不想用 VibeTrace, 在 settings.json 删掉 `hooks` 字段即可恢复。

## 卸载

```bash
# 1. 关闭 VibeTrace
# 2. 恢复 Claude Code settings:
#    删掉 ~/.claude/settings.json 里的 "hooks" 字段
# 3. 删 VibeTrace 应用
# 4. 数据文件: ~/Library/Application Support/dev.vibetrace.app/
```

## 高级: 自定义 vibe

```python
with trace("my-agent", vibe="pirate, dramatic, lots of exclamations!"):
    pass
```

`★ Insight ─────────────────────────────────────`
Vibe 是**任何自然语言描述**。VibeTrace 用关键词匹配做基础检测, 设置 `ANTHROPIC_API_KEY` 后会调用 LLM 做深度 vibe 偏离分析 (推荐)。
`─────────────────────────────────────────────────`

## 故障排查

| 问题 | 解决 |
|------|------|
| Dashboard 启动失败 | `pip install vibetrace[dashboard]` |
| Claude Code 没记录 | 检查 VibeTrace 是否运行, port 7842 是否被占用 |
| 桌面应用打包失败 | 看 GitHub Actions logs, 或本地 `npm run tauri build` |
| Loop 没检测到 | 调整 `vibetrace.configure(loop_detection_threshold=N)` |

## 反馈

提 issue 到 https://github.com/sakurairo/VibeTrace/issues
