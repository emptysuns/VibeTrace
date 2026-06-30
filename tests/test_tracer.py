"""
Tests for VibeTrace core.

Run: python -m pytest tests/
or:  python tests/test_tracer.py
"""
from __future__ import annotations

import os
import time
import tempfile
import sys
from pathlib import Path

# 让 import 找到 vibetrace
sys.path.insert(0, str(Path(__file__).parent.parent))


def setup_test_config():
    """为测试创建临时 DB。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["VIBETRACE_TEST_DB"] = tmp.name
    return tmp.name


def test_basic_trace():
    """基础 trace 创建和结束。"""
    from vibetrace import trace, event, configure
    from vibetrace.core.events import EventType, EventStatus

    db = setup_test_config()
    configure(sqlite_path=db)

    with trace("test-agent", vibe="calm") as t:
        t.set_input("hello")
        with event("step1", EventType.LLM_CALL, model="claude-haiku-4-5-20251001") as e:
            e.set_input("prompt")
            e.set_output("response", total_tokens=10, cost_usd=0.001)
        t.set_output("done")

    from vibetrace.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(db)
    traces = store.list_traces()
    assert len(traces) == 1, f"Expected 1 trace, got {len(traces)}"
    t = traces[0]
    assert t.name == "test-agent"
    assert t.vibe == "calm"
    assert t.total_events >= 3  # trace_start + step1 + trace_end
    assert t.total_tokens == 10
    assert abs(t.total_cost_usd - 0.001) < 1e-9
    print(f"✅ test_basic_trace: {t.name} ({t.total_events} events, {t.total_tokens} tokens)")


def test_loop_detection():
    """loop detection 应该触发。"""
    from vibetrace import trace, event, configure
    from vibetrace.core.events import EventType, EventStatus
    from vibetrace.core.context import get_config

    db = setup_test_config()
    configure(sqlite_path=db, loop_detection_threshold=3)

    with trace("loop-test") as t:
        for i in range(5):
            with event("reasoning", EventType.REASONING) as e:
                e.set_input("I'm trying the same thing again")
                time.sleep(0.01)
                e.set_output("Same plan")

    from vibetrace.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(db)
    result = store.get_trace_with_events(t.trace_id)
    events = result["events"]

    # 应该有一个 loop_detected 事件
    loop_events = [e for e in events if "loop" in (e.name or "").lower()]
    assert len(loop_events) >= 1, "Expected at least one loop_detected event"
    print(f"✅ test_loop_detection: detected {len(loop_events)} loop events")


def test_nested_traces():
    """嵌套 trace 通过装饰器。"""
    from vibetrace import trace_agent, configure

    db = setup_test_config()
    configure(sqlite_path=db)

    @trace_agent(name="outer")
    def outer():
        @trace_agent(name="inner")
        def inner():
            time.sleep(0.01)
            return "inner-result"
        return inner()

    result = outer()
    assert result == "inner-result"

    from vibetrace.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(db)
    traces = store.list_traces()
    assert len(traces) == 2, f"Expected 2 traces, got {len(traces)}"
    names = {t.name for t in traces}
    assert "outer" in names and "inner" in names
    print(f"✅ test_nested_traces: {names}")


def test_error_handling():
    """Trace 中的异常被正确捕获。"""
    from vibetrace import trace, event, configure
    from vibetrace.core.events import EventType

    db = setup_test_config()
    configure(sqlite_path=db)

    try:
        with trace("error-test") as t:
            with event("step1") as e:
                e.set_input("ok")
                e.set_output("ok")
            raise ValueError("test error")
    except ValueError:
        pass

    from vibetrace.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(db)
    t = store.list_traces()[0]
    assert t.status.value == "error"
    assert "ValueError" in (t.error or "")
    print(f"✅ test_error_handling: error correctly captured: {t.error}")


def test_storage_roundtrip():
    """Storage 保存和读取。"""
    from vibetrace import trace, configure
    from vibetrace.storage.sqlite_store import SQLiteStore

    db = setup_test_config()
    configure(sqlite_path=db)

    with trace("storage-test") as t:
        t.set_output({"answer": 42})

    store = SQLiteStore(db)
    result = store.get_trace_with_events(t.trace_id)
    assert result is not None
    assert result["trace"].output == {"answer": 42}
    print(f"✅ test_storage_roundtrip: output preserved correctly")


def test_analyst_rule_based():
    """规则引擎 analyst (不依赖 LLM)。"""
    from vibetrace import trace, event, configure
    from vibetrace.core.events import EventType
    from vibetrace.analyst.analyst import _rule_based_analyst

    db = setup_test_config()
    configure(sqlite_path=db)

    with trace("analyst-test", vibe="minimalist and calm") as t:
        with event("llm", EventType.LLM_CALL, model="claude-opus-4-8") as e:
            e.set_input("prompt" * 100)
            e.set_output("response" * 200, total_tokens=500, cost_usd=0.05)
        with event("err", EventType.TOOL_CALL) as e:
            e.set_input("bad input")
            e.set_error("Tool failed: bad input")
        t.set_output("done")

    from vibetrace.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(db)
    result = store.get_trace_with_events(t.trace_id)
    report = _rule_based_analyst(result["trace"], result["events"])
    assert "执行摘要" in report
    assert "根因分析" in report
    assert "模式检测" in report
    assert "改进建议" in report
    assert "Vibe 偏离检测" in report
    print(f"✅ test_analyst_rule_based: report length {len(report)} chars")


def test_concurrent_traces():
    """并发 trace 应该互不干扰。"""
    import threading
    from vibetrace import trace, event, configure
    from vibetrace.core.events import EventType

    db = setup_test_config()
    configure(sqlite_path=db)

    results = []

    def worker(i):
        with trace(f"worker-{i}") as t:
            with event("step", EventType.LLM_CALL) as e:
                e.set_input(f"worker {i}")
                e.set_output(f"output {i}", total_tokens=i, cost_usd=0.001 * i)
            results.append((i, t.trace_id))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    from vibetrace.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(db)
    traces = store.list_traces()
    assert len(traces) == 5, f"Expected 5 traces, got {len(traces)}"
    # 每个 trace 的 token 数应该匹配
    for t in traces:
        idx = int(t.name.split("-")[-1])
        assert t.total_tokens == idx, f"Token mismatch for {t.name}"
    print(f"✅ test_concurrent_traces: 5 concurrent traces, all correct")


def test_decorator_captures_args():
    """装饰器捕获参数和结果。"""
    from vibetrace import trace_agent, configure

    db = setup_test_config()
    configure(sqlite_path=db)

    @trace_agent(name="my-func")
    def my_func(x: int, y: int) -> int:
        return x * y

    result = my_func(3, 4)
    assert result == 12

    from vibetrace.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(db)
    t = store.list_traces()[0]
    assert t.name == "my-func"
    assert t.input is not None
    print(f"✅ test_decorator_captures_args: input={t.input}, output={t.output}")


def main():
    """Run all tests."""
    print("🧪 Running VibeTrace tests...\n")
    tests = [
        test_basic_trace,
        test_loop_detection,
        test_nested_traces,
        test_error_handling,
        test_storage_roundtrip,
        test_analyst_rule_based,
        test_concurrent_traces,
        test_decorator_captures_args,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    if failed == 0:
        print(f"✅ All {len(tests)} tests passed!")
    else:
        print(f"❌ {failed}/{len(tests)} tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
