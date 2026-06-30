"""
Demo Agent - 演示 VibeTrace 用法

这个 agent 模拟一个真实场景:
- 用户描述一个 vibe (设计风格)
- Agent 规划任务、调用工具、生成代码
- 故意加入一些 failure 模式用于展示 VibeTrace 的能力
"""
from __future__ import annotations

import time
import random
from vibetrace import trace, event, trace_agent, EventType


# === 模拟的 LLM / Tool ===

def fake_llm_call(prompt: str, model: str = "claude-haiku-4-5-20251001") -> dict:
    """模拟一次 LLM 调用。"""
    time.sleep(random.uniform(0.1, 0.3))
    return {
        "content": f"[{model} response to: {prompt[:60]}...]",
        "model": model,
        "prompt_tokens": len(prompt.split()) * 2,
        "completion_tokens": random.randint(50, 200),
    }


def fake_tool(name: str, input_data: str) -> dict:
    """模拟一次 tool call。"""
    time.sleep(random.uniform(0.05, 0.15))
    return {
        "tool": name,
        "input": input_data,
        "output": f"result for {name}({input_data})",
        "success": random.random() > 0.1,
    }


# === Demo agent ===

def run_demo(scenario: str = "happy"):
    """
    演示 agent。

    scenario:
    - "happy": 正常流程
    - "loop": 故意制造 loop，展示 detection
    - "error": 故意出错，展示根因分析
    - "vibe-deviation": 输出与 vibe 冲突的内容
    """
    vibes = {
        "happy": "calm, minimalist, generous whitespace",
        "loop": "calm, minimalist, generous whitespace",
        "error": "calm, minimalist, generous whitespace",
        "vibe-deviation": "calm, minimalist, generous whitespace",
    }
    vibe = vibes.get(scenario, "calm and minimalist")

    with trace("ui-generator", vibe=vibe, input={"scenario": scenario}) as t:
        t.add_tag(f"demo:{scenario}")

        # Step 1: 分析任务
        with event("plan-task", EventType.REASONING) as e:
            e.set_input("分析用户需求: 生成 minimalist UI")
            time.sleep(0.1)
            e.set_output("Plan: 1) 选色 2) 写 HTML 3) 验证")

        # Step 2: LLM call 1
        with event("llm-design", EventType.LLM_CALL, model="claude-opus-4-8") as e:
            e.set_input("Generate minimalist color palette")
            r = fake_llm_call("Generate minimalist color palette", "claude-opus-4-8")
            e.set_output(r["content"],
                         total_tokens=r["prompt_tokens"] + r["completion_tokens"],
                         cost_usd=0.045)

        # Step 3: Tool call 1
        with event("save-palette", EventType.TOOL_CALL, tool_name="file_write") as e:
            e.set_input({"path": "palette.json", "colors": ["#fff", "#000"]})
            r = fake_tool("file_write", "palette.json")
            e.set_output(r, success=r["success"])

        # Scenario-specific behavior
        if scenario == "loop":
            for i in range(4):
                with event(f"reasoning-attempt-{i}", EventType.REASONING) as e:
                    e.set_input("Try the same approach again, maybe it works this time")
                    time.sleep(0.05)
                    e.set_output("Same plan, different hope")

        elif scenario == "error":
            with event("validate-output", EventType.TOOL_CALL, tool_name="validator") as e:
                e.set_input({"check": "accessibility"})
                # 故意失败
                e.set_error("Validation failed: missing aria-label on submit button")
                e.set_output({"error": "missing aria-label"})

        elif scenario == "vibe-deviation":
            with event("llm-marketing", EventType.LLM_CALL, model="claude-opus-4-8") as e:
                e.set_input("Generate marketing copy")
                # 故意输出"loud"内容
                loud_output = "🚀🔥 WOW!!! This is the MOST AMAZING UI EVER!!! Check it out ASAP!!! 😱😱😱"
                e.set_output(loud_output, total_tokens=42, cost_usd=0.012)

        # Step 4: 写最终代码
        with event("llm-generate", EventType.LLM_CALL, model="claude-opus-4-8") as e:
            e.set_input("Generate final HTML")
            r = fake_llm_call("Generate final HTML", "claude-opus-4-8")
            e.set_output("<html>...</html> with calm minimalist design",
                         total_tokens=r["prompt_tokens"] + r["completion_tokens"],
                         cost_usd=0.067)

        t.set_output(f"Generated UI for scenario={scenario}")

    print(f"\n✅ Demo '{scenario}' complete!")
    print(f"   Run `vibetrace dashboard` to view, or `vibetrace list` to see in CLI.")


# === Multi-agent demo ===

@trace_agent(name="researcher", vibe="thoughtful and thorough")
def researcher_agent(query: str) -> str:
    """模拟一个 research agent."""
    with event("search", EventType.TOOL_CALL, tool_name="web_search") as e:
        e.set_input({"query": query, "limit": 5})
        e.set_output({"results": ["url1", "url2", "url3"]}, success=True)

    with event("summarize", EventType.LLM_CALL, model="claude-haiku-4-5-20251001") as e:
        e.set_input(f"Summarize: {query}")
        e.set_output("Summary of research findings",
                     total_tokens=1500, cost_usd=0.005)
    return "Research complete"


@trace_agent(name="writer", vibe="minimalist and clear")
def writer_agent(research: str) -> str:
    """模拟一个 writer agent."""
    with event("draft", EventType.LLM_CALL, model="claude-opus-4-8") as e:
        e.set_input(f"Write article based on: {research}")
        e.set_output("Final article body",
                     total_tokens=3000, cost_usd=0.085)
    return "Article complete"


@trace_agent(name="coordinator", vibe="calm orchestrator")
def coordinator_agent(query: str) -> str:
    """协调多个 sub-agent。"""
    research = researcher_agent(query)
    article = writer_agent(research)
    return article


if __name__ == "__main__":
    import sys
    scenario = sys.argv[1] if len(sys.argv) > 1 else "happy"
    if scenario == "all":
        for s in ["happy", "loop", "error", "vibe-deviation"]:
            run_demo(s)
    elif scenario == "multi":
        coordinator_agent("What is VibeTrace?")
    else:
        run_demo(scenario)
