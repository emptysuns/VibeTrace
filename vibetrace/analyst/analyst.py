"""
AI Analyst Agent

VibeTrace 的"智能层"。

输入: 一个 trace (events 列表 + 元信息)
输出: 自然语言报告，包含:
  1. 执行摘要 (执行什么、是否成功、花了多少钱/时间)
  2. 根因分析 (为什么失败/慢/贵)
  3. 模式检测 (loop、重复、hallucination)
  4. 改进建议 (具体可操作的修改)
  5. Vibe deviation (如果设了 vibe，对比实际行为)

设计原则:
- LLM 选择是 pluggable，默认用 Anthropic Claude (如果有 ANTHROPIC_API_KEY)
- Fallback: 如果没有 LLM API，用规则引擎（关键词检测、简单统计）
- 输出是 Markdown 格式，可直接渲染
"""
from __future__ import annotations

import os
import time
from typing import List, Optional, Dict, Any

from vibetrace.core.events import Trace, Event, EventType, EventStatus


# === Public API ===

def run_analyst(trace_obj: Trace, events: List[Event], model: str = "claude-haiku-4-5-20251001") -> Optional[str]:
    """
    运行 analyst，返回报告 (Markdown 字符串)。失败返回 None。

    优先用 LLM，没有 API key 就用 rule-based fallback。
    """
    # 尝试 LLM 分析
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        try:
            if os.environ.get("ANTHROPIC_API_KEY"):
                return _run_anthropic_analyst(trace_obj, events, model)
            else:
                return _run_openai_analyst(trace_obj, events, model)
        except Exception as e:
            print(f"[vibetrace] LLM analyst failed, falling back to rules: {e}")

    # Fallback: 规则引擎
    return _rule_based_analyst(trace_obj, events)


# === LLM-based Analyst ===

_ANALYST_SYSTEM_PROMPT = """你是一个 calm, insightful, minimalist 的 AI Agent 调试专家。

你的工作是分析一个 AI agent 运行的 trace，输出结构化报告。

报告应该:
1. **执行摘要** - 1-2 句，告诉用户发生了什么
2. **根因分析** - 如果有 error 或异常，定位到具体 event/步骤
3. **模式检测** - 识别 loop、重复、hallucination、cost hotspot、slow step
4. **改进建议** - 具体可操作的修改（改 prompt、换 model、加 schema、改变 vibe 等）
5. **Vibe 偏离检测** - 如果 trace 设了 vibe，对比实际行为
6. **Next step** - 1 个最值得做的下一步行动

风格:
- Calm, insightful, minimalist (像资深工程师)
- 不说废话，不重复 trace 内容
- 用 Markdown，简洁有力
- 总长 < 500 字 (但不要为了短而牺牲深度)
"""


def _build_analyst_prompt(trace_obj: Trace, events: List[Event]) -> str:
    """构造 user prompt: 序列化 trace。"""
    lines = []
    lines.append(f"# Trace: {trace_obj.name}")
    lines.append(f"- Trace ID: {trace_obj.trace_id}")
    lines.append(f"- Vibe: {trace_obj.vibe or '(none)'}")
    lines.append(f"- Status: {trace_obj.status.value}")
    lines.append(f"- Duration: {trace_obj.duration_ms:.0f}ms" if trace_obj.duration_ms else "- Duration: in progress")
    lines.append(f"- Total events: {trace_obj.total_events}")
    lines.append(f"- LLM calls: {trace_obj.total_llm_calls}, Tool calls: {trace_obj.total_tool_calls}")
    lines.append(f"- Total tokens: {trace_obj.total_tokens}")
    lines.append(f"- Total cost: ${trace_obj.total_cost_usd:.4f}")
    lines.append(f"- Error count: {trace_obj.error_count}")
    if trace_obj.error:
        lines.append(f"- Error: {trace_obj.error}")
    lines.append("")
    lines.append("## Events (timeline):")
    for i, e in enumerate(events):
        # 截断过长的内容
        input_str = _truncate_for_llm(e.input)
        output_str = _truncate_for_llm(e.output)
        lines.append(f"### [{i+1}] {e.event_type.value} - {e.name or '<no name>'}")
        lines.append(f"- time: {e.start_time:.3f}")
        if e.duration_ms:
            lines.append(f"- duration: {e.duration_ms:.1f}ms")
        if e.model:
            lines.append(f"- model: {e.model}")
        if e.total_tokens:
            lines.append(f"- tokens: {e.total_tokens} (${e.cost_usd or 0:.4f})")
        if e.status != EventStatus.OK:
            lines.append(f"- status: **{e.status.value}** {e.error or ''}")
        if input_str:
            lines.append(f"- input: {input_str}")
        if output_str:
            lines.append(f"- output: {output_str}")
        if e.metadata:
            for k, v in e.metadata.items():
                lines.append(f"- {k}: {v}")
        lines.append("")

    return "\n".join(lines)


def _truncate_for_llm(value: Any, max_len: int = 800) -> str:
    if value is None:
        return ""
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + f"... (truncated, total {len(s)} chars)"
    return s


def _run_anthropic_analyst(trace_obj: Trace, events: List[Event], model: str) -> str:
    """用 Anthropic SDK 分析。"""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic SDK not installed: pip install anthropic")

    client = anthropic.Anthropic()
    user_prompt = _build_analyst_prompt(trace_obj, events)

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_ANALYST_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    report = response.content[0].text

    # 保存到 storage
    _save_report(trace_obj.trace_id, report)
    return report


def _run_openai_analyst(trace_obj: Trace, events: List[Event], model: str) -> str:
    """用 OpenAI 兼容 API 分析。"""
    try:
        import openai
    except ImportError:
        raise RuntimeError("openai SDK not installed: pip install openai")

    client = openai.OpenAI()
    user_prompt = _build_analyst_prompt(trace_obj, events)

    response = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": _ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    report = response.choices[0].message.content
    _save_report(trace_obj.trace_id, report)
    return report


def _save_report(trace_id: str, report: str) -> None:
    try:
        from vibetrace.storage.sqlite_store import SQLiteStore
        from vibetrace.core.context import get_config
        store = SQLiteStore(get_config().sqlite_path)
        store.save_analyst_report(trace_id, report)
    except Exception:
        pass


# === Rule-based Fallback Analyst ===

def _rule_based_analyst(trace_obj: Trace, events: List[Event]) -> str:
    """
    不依赖 LLM 的分析器。

    用启发式规则生成报告。MVP 阶段够了，后续可加更多。
    """
    lines = ["# VibeTrace Analyst Report (rule-based)", ""]
    lines.append("> 💡 Set `ANTHROPIC_API_KEY` for AI-powered deep analysis.")
    lines.append("")

    # 1. 执行摘要
    status_emoji = "✅" if trace_obj.status == EventStatus.OK else "❌"
    lines.append("## 执行摘要")
    lines.append(
        f"{status_emoji} **{trace_obj.name}** "
        f"({_fmt_duration(trace_obj.duration_ms)}, "
        f"{trace_obj.total_events} events, "
        f"${trace_obj.total_cost_usd:.4f}, "
        f"{trace_obj.total_tokens} tokens)"
    )
    if trace_obj.vibe:
        lines.append(f"🎨 Vibe: *{trace_obj.vibe}*")
    if trace_obj.error:
        lines.append(f"⚠️ Error: `{trace_obj.error}`")
    lines.append("")

    # 2. 根因分析 (简单: 找第一个 error event)
    errors = [e for e in events if e.status == EventStatus.ERROR]
    if errors:
        lines.append("## 根因分析")
        first_error = errors[0]
        idx = events.index(first_error) + 1
        lines.append(f"首个错误出现在 **step {idx}** (`{first_error.name or first_error.event_type.value}`):")
        lines.append(f"> {first_error.error or '(no message)'}")
        if len(errors) > 1:
            lines.append(f"\n共 **{len(errors)}** 个错误 events。")
        lines.append("")

    # 3. 模式检测
    lines.append("## 模式检测")

    # 3a. Loop detection
    reasoning_texts = [
        str(e.input) for e in events
        if e.event_type == EventType.REASONING and e.input
    ]
    loops = _find_repeating_patterns(reasoning_texts, min_repeat=3)
    if loops:
        lines.append(f"🔁 **检测到循环**: {len(loops)} 个 reasoning 模式重复 ≥3 次")
        for sig, count in loops[:3]:
            lines.append(f"  - '{sig[:60]}...' × **{count}**")
    else:
        lines.append("✅ 未检测到明显循环")

    # 3b. Cost hotspot
    llm_events = [e for e in events if e.event_type == EventType.LLM_CALL and e.cost_usd]
    if llm_events:
        llm_events.sort(key=lambda e: e.cost_usd or 0, reverse=True)
        top = llm_events[0]
        lines.append(f"💰 **Cost hotspot**: 步骤 `{top.name or top.event_type.value}` 花费最多 (${top.cost_usd:.4f}, {top.total_tokens} tokens)")

    # 3c. Slow step
    timed = [e for e in events if e.duration_ms and e.duration_ms > 100]
    if timed:
        timed.sort(key=lambda e: e.duration_ms, reverse=True)
        top = timed[0]
        lines.append(f"🐢 **Slow step**: 步骤 `{top.name or top.event_type.value}` 耗时 {top.duration_ms:.0f}ms")

    # 3d. Error rate
    if trace_obj.error_count > 0:
        rate = trace_obj.error_count / max(trace_obj.total_events, 1) * 100
        lines.append(f"⚠️ **Error rate**: {trace_obj.error_count}/{trace_obj.total_events} = {rate:.1f}%")

    lines.append("")

    # 4. 改进建议 (rules)
    lines.append("## 改进建议")
    suggestions = _generate_rule_suggestions(trace_obj, events, loops)
    if suggestions:
        for s in suggestions:
            lines.append(f"- {s}")
    else:
        lines.append("- ✨ 看起来很健康！持续监控即可。")
    lines.append("")

    # 5. Vibe 偏离 (如果设了 vibe)
    if trace_obj.vibe:
        lines.append("## Vibe 偏离检测")
        lines.append(f"原始 vibe: *{trace_obj.vibe}*")
        # 简化: 检查输出里有没有明显冲突
        outputs = " ".join(str(e.output or "") for e in events)
        deviations = _detect_vibe_deviation(trace_obj.vibe, outputs)
        if deviations:
            for d in deviations:
                lines.append(f"- ⚠️ {d}")
        else:
            lines.append("- ✅ 未发现明显 vibe 偏离")
        lines.append("")

    return "\n".join(lines)


def _find_repeating_patterns(texts: List[str], min_repeat: int = 3) -> List[tuple]:
    """找重复出现的文本模式。"""
    counter: Dict[str, int] = {}
    for t in texts:
        sig = t.strip()[:100]
        if sig:
            counter[sig] = counter.get(sig, 0) + 1
    return [(sig, count) for sig, count in counter.items() if count >= min_repeat]


def _generate_rule_suggestions(trace_obj: Trace, events: List[Event], loops: List[tuple]) -> List[str]:
    suggestions = []
    if loops:
        suggestions.append(
            "🔁 添加 **max iterations** 限制或 **early stopping** 逻辑，避免无限循环"
        )
        suggestions.append(
            "🧠 在 prompt 中加入 'If you find yourself repeating, change your approach' 指令"
        )
    if trace_obj.total_cost_usd > 1.0:
        suggestions.append(
            f"💰 单次 trace 成本 ${trace_obj.total_cost_usd:.2f} 偏高，考虑用更便宜的 model (如 Haiku) 或减少 LLM 调用次数"
        )
    if trace_obj.error_count > 0:
        suggestions.append(
            "🛡️ 添加 retry + fallback 逻辑 (e.g. exponential backoff)"
        )
        suggestions.append(
            "📋 给 tool call 加 Pydantic schema，让 LLM 输出更可预测"
        )
    if trace_obj.total_llm_calls > 10:
        suggestions.append(
            f"🤖 调了 {trace_obj.total_llm_calls} 次 LLM，考虑 batch 多个 sub-task 一次完成"
        )
    if not suggestions:
        suggestions.append("✨ 没有明显问题，保持现状")
    return suggestions


def _detect_vibe_deviation(vibe: str, outputs: str) -> List[str]:
    """简单的 vibe 偏离检测: 用关键词匹配。"""
    deviations = []
    vibe_lower = vibe.lower()
    outputs_lower = outputs.lower()

    # 极简 vibe 检测
    if "minimalist" in vibe_lower or "minimal" in vibe_lower or "简洁" in vibe_lower:
        # 检测冗长输出
        if len(outputs) > 5000:
            deviations.append("输出过长 (~5000+ chars)，可能违反 'minimalist' vibe")

    if "calm" in vibe_lower or "平静" in vibe_lower:
        if any(kw in outputs_lower for kw in ["urgent", "panic", "asap", "error!!!", "崩溃"]):
            deviations.append("输出包含 panic/urgent 词汇，与 'calm' vibe 冲突")

    if "professional" in vibe_lower or "专业" in vibe_lower:
        if any(kw in outputs_lower for kw in ["lol", "haha", "嘿嘿", "yeah", "omg"]):
            deviations.append("输出包含非正式词汇，与 'professional' vibe 冲突")

    if "happy" in vibe_lower or "cheerful" in vibe_lower or "愉悦" in vibe_lower:
        if "error" in outputs_lower or "failed" in outputs_lower:
            deviations.append("输出包含 error/failed，可能违反 'happy' vibe")

    return deviations


def _fmt_duration(ms: Optional[float]) -> str:
    if ms is None:
        return "in progress"
    if ms < 1000:
        return f"{ms:.0f}ms"
    if ms < 60000:
        return f"{ms/1000:.2f}s"
    return f"{ms/60000:.2f}min"
