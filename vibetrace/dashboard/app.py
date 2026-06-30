"""
Streamlit Dashboard

VibeTrace 的可视化层。

启动: vibetrace dashboard
访问: http://localhost:8501

设计目标:
- Calm, insightful, minimalist (深色模式优先)
- 4 个主要视图: Trace 列表 / Timeline / Graph / Analyst 报告
- 一键 drill-down: 从 trace 列表 → timeline → 单个 event 详情
- Vibe check 面板 (独特功能)

为什么选 Streamlit:
- 纯 Python, 无需前端
- 几分钟做出专业 dashboard
- 后续可平滑迁移到 React (但 MVP 不需要)
"""
from __future__ import annotations

import sys
import os
import time
from typing import Optional

import streamlit as st

from vibetrace.core.events import Event, Trace, EventType, EventStatus
from vibetrace.core.context import get_config
from vibetrace.storage.sqlite_store import SQLiteStore


# === Page Config ===

st.set_page_config(
    page_title="VibeTrace 🪄🔍",
    page_icon="🪄",
    layout="wide",
    initial_sidebar_state="expanded",
)


# === Custom CSS - calm, insightful, minimalist vibe ===

_CUSTOM_CSS = """
<style>
    /* 深色模式基调 */
    .stApp {
        background: linear-gradient(180deg, #0e1117 0%, #161b22 100%);
    }

    /* 字体 */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
    }

    /* 标题 - calm gradient */
    h1 {
        background: linear-gradient(90deg, #a78bfa 0%, #60a5fa 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 600;
    }

    /* Metric 卡片 - 极简风 */
    [data-testid="stMetric"] {
        background: rgba(167, 139, 250, 0.05);
        border: 1px solid rgba(167, 139, 250, 0.15);
        border-radius: 8px;
        padding: 12px;
    }

    /* Event 卡片 */
    .event-card {
        background: rgba(22, 27, 34, 0.6);
        border-left: 3px solid #a78bfa;
        border-radius: 6px;
        padding: 12px 16px;
        margin: 8px 0;
        transition: all 0.2s ease;
    }
    .event-card:hover {
        background: rgba(167, 139, 250, 0.08);
        transform: translateX(2px);
    }
    .event-card.error {
        border-left-color: #f87171;
    }
    .event-card.llm {
        border-left-color: #60a5fa;
    }
    .event-card.tool {
        border-left-color: #34d399;
    }
    .event-card.reasoning {
        border-left-color: #fbbf24;
    }

    /* Code block */
    .code-block {
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 12px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        overflow-x: auto;
        color: #c9d1d9;
    }

    /* Tag pill */
    .tag-pill {
        display: inline-block;
        background: rgba(167, 139, 250, 0.15);
        color: #a78bfa;
        border-radius: 12px;
        padding: 2px 10px;
        font-size: 11px;
        margin: 0 4px;
    }

    /* Vibe badge */
    .vibe-badge {
        background: linear-gradient(135deg, #a78bfa 0%, #60a5fa 100%);
        color: white;
        border-radius: 6px;
        padding: 4px 12px;
        font-size: 12px;
        font-style: italic;
        display: inline-block;
    }

    /* Hide Streamlit branding for clean look */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
"""


# === Helpers ===

@st.cache_resource
def get_store() -> SQLiteStore:
    return SQLiteStore(get_config().sqlite_path)


def format_duration(ms: Optional[float]) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f}ms"
    if ms < 60000:
        return f"{ms/1000:.2f}s"
    return f"{ms/60000:.2f}min"


def format_cost(cost: Optional[float]) -> str:
    if cost is None or cost == 0:
        return "$0.00"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def event_color_class(event: Event) -> str:
    if event.status == EventStatus.ERROR:
        return "error"
    if event.event_type == EventType.LLM_CALL:
        return "llm"
    if event.event_type == EventType.TOOL_CALL:
        return "tool"
    if event.event_type == EventType.REASONING:
        return "reasoning"
    return ""


def event_emoji(event_type: EventType) -> str:
    """事件类型 → emoji。视觉化第一原则。"""
    return {
        EventType.LLM_CALL: "🤖",
        EventType.TOOL_CALL: "🔧",
        EventType.REASONING: "💭",
        EventType.MEMORY_READ: "📖",
        EventType.MEMORY_WRITE: "✏️",
        EventType.DECISION: "🔀",
        EventType.ERROR: "❌",
        EventType.RETRY: "🔁",
        EventType.HUMAN_INPUT: "👤",
        EventType.TRACE_START: "▶️",
        EventType.TRACE_END: "⏹️",
    }.get(event_type, "•")


# === Pages ===

def page_trace_list(store: SQLiteStore):
    """Trace 列表页 - 仪表板首页。"""
    st.title("VibeTrace 🪄🔍")
    st.caption("AI Agent 的可观测性、调试与可靠性工具。calm, insightful, minimalist.")

    # 全局统计
    stats = store.get_stats()
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Traces", stats["total_traces"])
    with col2:
        st.metric("Errors", stats["error_traces"], delta=None,
                  delta_color="inverse" if stats["error_traces"] > 0 else "off")
    with col3:
        st.metric("Total Tokens", f"{stats['total_tokens']:,}")
    with col4:
        st.metric("Total Cost", format_cost(stats["total_cost_usd"]))
    with col5:
        st.metric("Avg Duration", format_duration(stats["avg_duration_ms"]))

    st.divider()

    # 筛选
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search = st.text_input("🔍 Search by name", "")
    with col2:
        status_filter = st.selectbox("Status", ["all", "ok", "error"])
    with col3:
        limit = st.selectbox("Limit", [25, 50, 100, 200], index=1)

    # 查询
    status_arg = None if status_filter == "all" else status_filter
    name_arg = search if search else None
    traces = store.list_traces(limit=limit, status=status_arg, name_contains=name_arg)

    if not traces:
        st.info("📭 还没有 trace。先去运行你的 agent！\n\n```python\nfrom vibetrace import trace\nwith trace('my-agent'):\n    # ...\n```")
        return

    # Trace 列表
    st.subheader(f"📋 {len(traces)} traces")

    for t in traces:
        status_emoji = "✅" if t.status == EventStatus.OK else "❌"
        col1, col2, col3, col4, col5, col6 = st.columns([3, 2, 2, 2, 2, 1])

        with col1:
            st.markdown(f"### {status_emoji} {t.name}")
            if t.vibe:
                st.markdown(f'<span class="vibe-badge">🎨 {t.vibe}</span>', unsafe_allow_html=True)
        with col2:
            st.caption(f"⏱️ {format_duration(t.duration_ms)}")
            st.caption(f"🕐 {time.strftime('%H:%M:%S', time.localtime(t.start_time))}")
        with col3:
            st.caption(f"🤖 {t.total_llm_calls} LLM · 🔧 {t.total_tool_calls} tools")
        with col4:
            st.caption(f"📊 {t.total_tokens:,} tokens")
        with col5:
            st.caption(f"💰 {format_cost(t.total_cost_usd)}")
        with col6:
            if st.button("View", key=f"view_{t.trace_id}"):
                st.session_state["selected_trace_id"] = t.trace_id
                st.rerun()

        st.divider()


def page_trace_detail(store: SQLiteStore, trace_id: str):
    """Trace 详情页 - Timeline + Graph + Analyst。"""
    result = store.get_trace_with_events(trace_id)
    if result is None:
        st.error(f"Trace {trace_id} not found")
        return

    t: Trace = result["trace"]
    events: list = result["events"]

    # Header
    col1, col2 = st.columns([4, 1])
    with col1:
        status_emoji = "✅" if t.status == EventStatus.OK else "❌"
        st.title(f"{status_emoji} {t.name}")
        if t.vibe:
            st.markdown(f'<span class="vibe-badge">🎨 {t.vibe}</span>', unsafe_allow_html=True)
        if t.error:
            st.error(f"❌ {t.error}")
    with col2:
        if st.button("← Back to list"):
            st.session_state.pop("selected_trace_id", None)
            st.rerun()

    # 元数据卡片
    st.divider()
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Duration", format_duration(t.duration_ms))
    with col2:
        st.metric("Events", t.total_events)
    with col3:
        st.metric("LLM calls", t.total_llm_calls)
    with col4:
        st.metric("Tool calls", t.total_tool_calls)
    with col5:
        st.metric("Tokens", f"{t.total_tokens:,}")
    with col6:
        st.metric("Cost", format_cost(t.total_cost_usd))

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["⏱️ Timeline", "🌳 Graph", "🧠 Analyst", "🎨 Vibe Check"])

    with tab1:
        page_timeline(events)

    with tab2:
        page_graph(events)

    with tab3:
        page_analyst(store, t, events)

    with tab4:
        page_vibe_check(t, events)


def page_timeline(events: list):
    """Timeline 视图 - 按时间顺序的事件流。"""
    st.subheader(f"⏱️ Timeline ({len(events)} events)")

    if not events:
        st.info("No events recorded")
        return

    base_time = events[0].start_time

    for i, e in enumerate(events):
        offset_ms = (e.start_time - base_time) * 1000
        color_class = event_color_class(e)
        emoji = event_emoji(e.event_type)
        status_emoji = "❌" if e.status == EventStatus.ERROR else ""

        # Event card
        with st.container():
            col1, col2 = st.columns([1, 11])
            with col1:
                st.caption(f"+{offset_ms:.0f}ms")
            with col2:
                # Header
                st.markdown(
                    f"**{emoji} {e.event_type.value}** · `{e.name or '<unnamed>'}` "
                    f"{status_emoji} "
                    f"<span class='tag-pill'>{format_duration(e.duration_ms)}</span>",
                    unsafe_allow_html=True,
                )

                # Key info badges
                badges = []
                if e.model:
                    badges.append(f"🤖 {e.model}")
                if e.total_tokens:
                    badges.append(f"📊 {e.total_tokens} tokens")
                if e.cost_usd:
                    badges.append(f"💰 {format_cost(e.cost_usd)}")
                if badges:
                    st.caption(" · ".join(badges))

                # Expandable details
                with st.expander("Details", expanded=False):
                    if e.input is not None:
                        st.markdown("**Input:**")
                        st.markdown(f'<div class="code-block">{_escape(str(e.input))}</div>', unsafe_allow_html=True)
                    if e.output is not None:
                        st.markdown("**Output:**")
                        st.markdown(f'<div class="code-block">{_escape(str(e.output))}</div>', unsafe_allow_html=True)
                    if e.error:
                        st.error(f"Error: {e.error}")
                    if e.metadata:
                        st.markdown("**Metadata:**")
                        st.json(e.metadata)


def page_graph(events: list):
    """Graph/Tree 视图 - 父子关系。"""
    st.subheader("🌳 Execution Graph")

    if not events:
        st.info("No events")
        return

    # Build tree
    by_parent: dict = {}
    roots = []
    for e in events:
        parent = e.parent_id
        if parent is None:
            roots.append(e)
        else:
            by_parent.setdefault(parent, []).append(e)

    def render_node(e: Event, depth: int = 0):
        indent = "  " * depth
        emoji = event_emoji(e.event_type)
        status = "❌" if e.status == EventStatus.ERROR else "✅"
        cost_str = f" · ${e.cost_usd:.4f}" if e.cost_usd else ""
        dur_str = f" · {format_duration(e.duration_ms)}" if e.duration_ms else ""

        st.markdown(
            f"{indent}{emoji} **{e.event_type.value}** · `{e.name or '<unnamed>'}` "
            f"{status}{dur_str}{cost_str}"
        )

        # Children
        children = by_parent.get(e.span_id, [])
        for child in children:
            render_node(child, depth + 1)

    st.caption(f"📊 {len(roots)} root(s), {len(events)} total events")
    st.divider()

    for root in roots:
        with st.container():
            render_node(root)


def page_analyst(store: SQLiteStore, t: Trace, events: list):
    """Analyst 报告面板。"""
    st.subheader("🧠 AI Analyst Report")

    # 优先从 storage 读
    report = store.get_analyst_report(t.trace_id)

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Re-run analyst"):
            with st.spinner("Analyzing..."):
                from vibetrace.analyst.analyst import run_analyst
                report = run_analyst(t, events)
            st.rerun()

    if report:
        st.markdown(report)
    else:
        st.info("🤔 No analyst report yet. Click 'Re-run analyst' to generate one.")


def page_vibe_check(t: Trace, events: list):
    """Vibe Check 面板 - VibeTrace 独特功能。"""
    st.subheader("🎨 Vibe Check")

    if not t.vibe:
        st.info("这个 trace 没有设置 vibe. 用 `with trace('name', vibe='your vibe here')` 来设置.")
        return

    st.markdown(f"**原始 vibe**: <span class='vibe-badge'>{t.vibe}</span>", unsafe_allow_html=True)
    st.divider()

    # 简单 vibe check
    outputs = " ".join(str(e.output or "") for e in events if e.output)
    inputs = " ".join(str(e.input or "") for e in events if e.input)
    full_text = outputs + " " + inputs

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 长度")
        st.metric("总输出字符数", len(outputs))
        if "minimalist" in t.vibe.lower() or "minimal" in t.vibe.lower() or "简洁" in t.vibe:
            if len(outputs) > 5000:
                st.warning("⚠️ 输出过长，可能违反 'minimalist' vibe")
            else:
                st.success("✅ 长度与 'minimalist' vibe 一致")

    with col2:
        st.markdown("### 语调")
        vibe_lower = t.vibe.lower()
        if "calm" in vibe_lower or "平静" in t.vibe:
            urgent_words = ["urgent", "panic", "asap", "crash", "崩溃", "急"]
            hits = [w for w in urgent_words if w.lower() in full_text.lower()]
            if hits:
                st.warning(f"⚠️ 发现 urgent 词汇: {hits}")
            else:
                st.success("✅ 语调 calm")
        elif "professional" in vibe_lower or "专业" in t.vibe:
            informal = ["lol", "haha", "omg", "嘿嘿", "yeah"]
            hits = [w for w in informal if w.lower() in full_text.lower()]
            if hits:
                st.warning(f"⚠️ 非正式词汇: {hits}")
            else:
                st.success("✅ 语调 professional")
        else:
            st.info("无具体语调规则可检查")

    st.divider()
    st.caption("💡 Vibe Check 是 MVP 功能。完整版会调用 LLM 做深度 vibe 偏离分析。")


def _escape(s: str) -> str:
    """HTML escape for safe rendering."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# === Main ===

def main():
    # Inject custom CSS
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)

    store = get_store()

    # Sidebar
    with st.sidebar:
        st.markdown("### 🪄 VibeTrace")
        st.caption("Agent observability & debug")
        st.divider()
        st.markdown("**Quick links**")
        if st.button("📋 All traces"):
            st.session_state.pop("selected_trace_id", None)
            st.rerun()
        st.divider()
        st.markdown("**Storage**")
        st.caption(f"📁 {get_config().sqlite_path}")
        st.caption("💡 Set ANTHROPIC_API_KEY for AI analyst")

    # Routing
    if "selected_trace_id" in st.session_state:
        page_trace_detail(store, st.session_state["selected_trace_id"])
    else:
        page_trace_list(store)


if __name__ == "__main__":
    main()
