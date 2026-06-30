"""
CLI 入口

Usage:
    vibetrace dashboard        # 启动 Streamlit dashboard
    vibetrace list             # 列出最近 traces
    vibetrace show <trace_id>  # 显示 trace 详情
    vibetrace stats            # 全局统计
    vibetrace analyze <id>     # 单独运行 analyst
    vibetrace clean            # 删除所有 traces
    vibetrace demo             # 运行 demo agent
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Optional


def cmd_dashboard(args):
    """启动 Streamlit dashboard。"""
    try:
        import streamlit
    except ImportError:
        print("❌ Streamlit not installed: pip install vibetrace[dashboard]")
        sys.exit(1)

    import subprocess
    from vibetrace.dashboard.app import main as dashboard_main

    # Streamlit 通过 run 运行自己的 server
    print("🪄 Starting VibeTrace dashboard at http://localhost:8501")
    print("   Press Ctrl+C to stop.\n")

    # 调用 streamlit run 自己的 app
    app_path = __import__("vibetrace").dashboard.app.__file__
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", app_path,
         "--server.port", str(args.port),
         "--server.headless", "true",
         "--theme.base", "dark",
         "--theme.primaryColor", "#a78bfa",
         "--theme.backgroundColor", "#0e1117",
         "--theme.secondaryBackgroundColor", "#161b22",
         "--theme.textColor", "#c9d1d9",
         "--theme.font", "sans serif"],
    )


def cmd_list(args):
    """列出最近 traces。"""
    from vibetrace.storage.sqlite_store import SQLiteStore
    from vibetrace.core.context import get_config
    from vibetrace.core.events import EventStatus

    store = SQLiteStore(get_config().sqlite_path)
    traces = store.list_traces(limit=args.limit)

    if not traces:
        print("📭 No traces found. Run an agent with `with trace(...):` first.")
        return

    print(f"📋 Last {len(traces)} traces:\n")
    print(f"{'STATUS':<8} {'NAME':<30} {'DURATION':<12} {'EVENTS':<8} {'TOKENS':<10} {'COST':<10} {'TIME':<20}")
    print("─" * 100)

    for t in traces:
        status = "✅ OK" if t.status == EventStatus.OK else f"❌ {t.status.value}"
        name = (t.name or "")[:28]
        dur = f"{t.duration_ms:.0f}ms" if t.duration_ms else "—"
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t.start_time))
        cost = f"${t.total_cost_usd:.4f}"
        print(f"{status:<8} {name:<30} {dur:<12} {t.total_events:<8} {t.total_tokens:<10} {cost:<10} {ts}")

    print(f"\n💡 Run `vibetrace dashboard` to explore visually.")


def cmd_show(args):
    """显示单个 trace 详情。"""
    from vibetrace.storage.sqlite_store import SQLiteStore
    from vibetrace.core.context import get_config
    from vibetrace.core.events import EventStatus

    store = SQLiteStore(get_config().sqlite_path)
    result = store.get_trace_with_events(args.trace_id)
    if not result:
        print(f"❌ Trace {args.trace_id} not found")
        sys.exit(1)

    t = result["trace"]
    events = result["events"]
    status = "✅ OK" if t.status == EventStatus.OK else f"❌ {t.status.value}"

    print(f"\n{'='*60}")
    print(f"  {status}  {t.name}")
    if t.vibe:
        print(f"  🎨 Vibe: {t.vibe}")
    print(f"{'='*60}")
    print(f"  Trace ID:  {t.trace_id}")
    print(f"  Duration:  {t.duration_ms:.0f}ms" if t.duration_ms else "  Duration:  —")
    print(f"  Events:    {t.total_events}  (LLM: {t.total_llm_calls}, Tool: {t.total_tool_calls})")
    print(f"  Tokens:    {t.total_tokens}")
    print(f"  Cost:      ${t.total_cost_usd:.4f}")
    print(f"  Errors:    {t.error_count}")
    if t.error:
        print(f"  Trace Error: {t.error}")
    print(f"{'='*60}\n")

    print("📋 Events:\n")
    for i, e in enumerate(events):
        emoji = {
            "llm.call": "🤖", "tool.call": "🔧", "reasoning": "💭",
            "error": "❌", "trace.start": "▶️", "trace.end": "⏹️",
        }.get(e.event_type.value, "•")
        status_mark = "❌" if e.status == EventStatus.ERROR else "  "
        dur = f"{e.duration_ms:.0f}ms" if e.duration_ms else "—"
        cost = f"${e.cost_usd:.4f}" if e.cost_usd else "—"
        tokens = str(e.total_tokens) if e.total_tokens else "—"
        print(f"  {i+1:>3}. {status_mark} {emoji} {e.event_type.value:<14} {e.name or '—':<25} {dur:>8}  {tokens:>6}  {cost:>8}")
        if e.error:
            print(f"       ↳ ❌ {e.error}")

    # Analyst
    report = store.get_analyst_report(t.trace_id)
    if report:
        print(f"\n{'─'*60}")
        print("🧠 Analyst Report:")
        print(f"{'─'*60}\n")
        print(report)
    else:
        print(f"\n💡 Run `vibetrace analyze {t.trace_id}` to generate analyst report.")


def cmd_stats(args):
    """显示全局统计。"""
    from vibetrace.storage.sqlite_store import SQLiteStore
    from vibetrace.core.context import get_config

    store = SQLiteStore(get_config().sqlite_path)
    s = store.get_stats()

    print("\n📊 VibeTrace Statistics\n")
    print(f"  Total traces:     {s['total_traces']}")
    print(f"  Error traces:     {s['error_traces']}")
    print(f"  Total LLM calls:  {s['total_llm_calls']}")
    print(f"  Total tool calls: {s['total_tool_calls']}")
    print(f"  Total tokens:     {s['total_tokens']:,}")
    print(f"  Total cost:       ${s['total_cost_usd']:.4f}")
    print(f"  Avg duration:     {s['avg_duration_ms']:.0f}ms")
    print()


def cmd_analyze(args):
    """单独运行 analyst。"""
    from vibetrace.storage.sqlite_store import SQLiteStore
    from vibetrace.core.context import get_config
    from vibetrace.analyst.analyst import run_analyst

    store = SQLiteStore(get_config().sqlite_path)
    result = store.get_trace_with_events(args.trace_id)
    if not result:
        print(f"❌ Trace {args.trace_id} not found")
        sys.exit(1)

    t = result["trace"]
    events = result["events"]

    print(f"🧠 Analyzing trace {t.trace_id} ({t.name})...")
    report = run_analyst(t, events)
    print(f"\n{'─'*60}")
    print(report)
    print(f"{'─'*60}\n")
    print(f"✅ Saved to trace {t.trace_id}")


def cmd_clean(args):
    """删除所有 traces。"""
    from vibetrace.storage.sqlite_store import SQLiteStore
    from vibetrace.core.context import get_config

    if not args.yes:
        confirm = input("⚠️  Delete ALL traces? This cannot be undone. [y/N] ")
        if confirm.lower() != "y":
            print("Cancelled.")
            return

    store = SQLiteStore(get_config().sqlite_path)
    conn = store._get_conn()
    cursor = conn.execute("DELETE FROM events")
    events_deleted = cursor.rowcount
    cursor = conn.execute("DELETE FROM traces")
    traces_deleted = cursor.rowcount
    conn.commit()
    print(f"✅ Deleted {traces_deleted} traces and {events_deleted} events.")


def cmd_demo(args):
    """运行一个 demo agent 演示。"""
    print("🎬 Running demo agent...\n")
    from examples.demo_agent import run_demo
    run_demo()


def main():
    parser = argparse.ArgumentParser(
        prog="vibetrace",
        description="🪄 VibeTrace - AI Agent observability & debug toolkit",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # dashboard
    p_dash = subparsers.add_parser("dashboard", help="Launch Streamlit dashboard")
    p_dash.add_argument("--port", type=int, default=8501, help="Port (default: 8501)")
    p_dash.set_defaults(func=cmd_dashboard)

    # list
    p_list = subparsers.add_parser("list", help="List recent traces")
    p_list.add_argument("--limit", type=int, default=20, help="Number of traces (default: 20)")
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = subparsers.add_parser("show", help="Show trace details")
    p_show.add_argument("trace_id", help="Trace ID (full or prefix)")
    p_show.set_defaults(func=cmd_show)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show global statistics")
    p_stats.set_defaults(func=cmd_stats)

    # analyze
    p_an = subparsers.add_parser("analyze", help="Run analyst on a trace")
    p_an.add_argument("trace_id", help="Trace ID")
    p_an.set_defaults(func=cmd_analyze)

    # clean
    p_clean = subparsers.add_parser("clean", help="Delete all traces")
    p_clean.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_clean.set_defaults(func=cmd_clean)

    # demo
    p_demo = subparsers.add_parser("demo", help="Run demo agent")
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
