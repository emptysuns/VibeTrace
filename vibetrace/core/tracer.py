"""
Tracer 引擎 - VibeTrace 的"心脏"

这是用户直接交互的 API:
- `trace()` - 创建/管理一个 trace (context manager)
- `event()` - 记录一个事件 (context manager)
- `trace_agent()` - 装饰器，给函数/方法自动添加追踪
- `record_event()` - 手动记录一个事件 (高级用法)

设计目标:
- 零侵入: 不需要修改业务代码结构
- 类型安全: 使用 dataclass + enum，IDE 友好
- 异步安全: 基于 contextvars，自动处理嵌套和并发
- 错误安全: 即使 storage 失败也不影响业务
"""
from __future__ import annotations

import functools
import time
import traceback
from contextlib import contextmanager
from typing import Any, Callable, Optional, TypeVar, ParamSpec

from vibetrace.core.events import (
    Event,
    Trace,
    Span,
    EventType,
    EventStatus,
)
from vibetrace.core.context import (
    ActiveTrace,
    ActiveSpan,
    get_current_trace,
    get_current_span,
    _set_current_trace,
    _push_span,
    _pop_span,
    _reset_current_trace,
    get_config,
)


P = ParamSpec("P")
R = TypeVar("R")


# === Storage accessor (lazy import 避免循环依赖) ===

_storage = None


def _get_storage():
    """Lazy-load storage. 第一次访问时初始化。"""
    global _storage
    if _storage is None or _storage.db_path != get_config().sqlite_path:
        # 路径变了 (测试场景): 关闭旧的,创建新的
        if _storage is not None:
            try:
                _storage.close()
            except Exception:
                pass
        from vibetrace.storage.sqlite_store import SQLiteStore
        cfg = get_config()
        _storage = SQLiteStore(cfg.sqlite_path)
    return _storage


def _reset_storage():
    """重置 storage 单例 (测试用)."""
    global _storage
    if _storage is not None:
        try:
            _storage.close()
        except Exception:
            pass
    _storage = None


# === Loop detection ===

_loop_counter: dict = {}  # trace_id -> {signature: count}


def _check_loop(trace_id: str, signature: str) -> int:
    """检测 loop: 相同 signature 重复出现。返回当前计数。"""
    cfg = get_config()
    if trace_id not in _loop_counter:
        _loop_counter[trace_id] = {}
    counter = _loop_counter[trace_id]
    counter[signature] = counter.get(signature, 0) + 1
    return counter[signature]


def _reset_loop_counter(trace_id: str) -> None:
    _loop_counter.pop(trace_id, None)


# === Public API ===

@contextmanager
def _create_trace(
    name: str = "agent-run",
    vibe: str = "",
    input: Any = None,
    **metadata,
):
    """
    实际创建 trace 的 context manager (内部 API)。
    public `trace()` 函数包装它以提供 proxy 句柄。
    """
    cfg = get_config()
    storage = _get_storage()

    # 如果已有父 trace，嵌套 (作为 child)。否则创建新 root。
    parent = get_current_trace()
    trace_obj = Trace(
        name=name,
        vibe=vibe,
        input=input if cfg.capture_prompts else _redact(input, cfg.redact_keys),
        metadata=metadata,
    )

    active = ActiveTrace(trace=trace_obj, on_finish=storage.save_trace)
    token = _set_current_trace(active)

    # 先存 trace (parent) 再存 events (children with FK)
    # 把 trace 的初始 metadata 持久化，确保后续 events 的外键能通过
    try:
        storage.save_trace(trace_obj, [])
    except Exception as e:
        print(f"[vibetrace] save trace init failed: {e}")

    # 记录 trace.start 事件
    start_event = Event(
        trace_id=trace_obj.trace_id,
        event_type=EventType.TRACE_START,
        name=name,
        input=input,
        metadata={"vibe": vibe, **metadata},
    )
    active.add_event(start_event)
    storage.save_event(start_event)

    try:
        yield active
        trace_obj.finish(EventStatus.OK)
    except Exception as e:
        trace_obj.finish(EventStatus.ERROR)
        trace_obj.error = f"{type(e).__name__}: {e}"
        # 记录 error 事件
        err_event = Event(
            trace_id=trace_obj.trace_id,
            event_type=EventType.ERROR,
            name="trace.exception",
            status=EventStatus.ERROR,
            error=str(e),
            metadata={"traceback": traceback.format_exc()},
        )
        active.add_event(err_event)
        storage.save_event(err_event)
        raise
    finally:
        # 记录 trace.end 事件
        end_event = Event(
            trace_id=trace_obj.trace_id,
            event_type=EventType.TRACE_END,
            name=name,
            end_time=time.time(),
        )
        active.add_event(end_event)
        storage.save_event(end_event)

        # 聚合统计 & 持久化
        active.update_stats()
        try:
            storage.save_trace(trace_obj, active.events)
        except Exception as e:
            # Storage 失败不能影响业务
            print(f"[vibetrace] storage save failed: {e}")

        # 关键: 强制 WAL checkpoint, 让外部 connection (dashboard) 能看到数据
        try:
            if hasattr(storage, "_force_checkpoint"):
                storage._force_checkpoint()
        except Exception:
            pass

        # 触发 analyst (异步 / 后台 / 同步 都可，MVP 同步)
        if cfg.analyst_enabled:
            try:
                _maybe_run_analyst(trace_obj, active.events)
            except Exception as e:
                print(f"[vibetrace] analyst failed: {e}")

        # 清理
        _reset_loop_counter(trace_obj.trace_id)
        _reset_current_trace(token)


class _TraceProxy:
    """
    `with trace(...) as t:` 中的 `t` 代理。

    提供方便的方法：set_input / set_output / add_tag / set_metadata。
    """

    def __init__(self, active: ActiveTrace):
        self._active = active

    @property
    def trace_id(self) -> str:
        return self._active.trace.trace_id

    def set_input(self, value: Any) -> None:
        self._active.trace.input = value

    def set_output(self, value: Any) -> None:
        self._active.trace.output = value

    def add_tag(self, tag: str) -> None:
        if tag not in self._active.trace.tags:
            self._active.trace.tags.append(tag)

    def set_metadata(self, key: str, value: Any) -> None:
        self._active.trace.metadata[key] = value

    def record(self, event: Event) -> None:
        """手动添加一个事件。"""
        event.trace_id = self._active.trace.trace_id
        self._active.add_event(event)
        _get_storage().save_event(event)


# Public API: 包装 _create_trace，提供 proxy 句柄
def trace(name: str = "agent-run", vibe: str = "", input: Any = None, **metadata):
    """
    创建一个 trace context manager。

    用法:
        with trace("my-agent", vibe="calm and minimalist") as t:
            t.set_input("user query")
            # ... 业务代码 ...
            t.set_output("final result")
    """
    cm = _create_trace(name=name, vibe=vibe, input=input, **metadata)
    return _TraceContextManagerProxy(cm, name, vibe, input, metadata)


class _TraceContextManagerProxy:
    def __init__(self, inner, name, vibe, input, metadata):
        self._inner = inner
        self._name = name
        self._vibe = vibe
        self._input = input
        self._metadata = metadata

    def __enter__(self) -> _TraceProxy:
        active = self._inner.__enter__()
        return _TraceProxy(active)

    def __exit__(self, *args):
        return self._inner.__exit__(*args)


@contextmanager
def event(
    name: str,
    event_type: EventType = EventType.LLM_CALL,
    **kwargs,
):
    """
    Context manager: 记录一个事件。

    用法:
        with event("call-claude", event_type=EventType.LLM_CALL, model="claude-opus-4-8") as e:
            e.set_input(prompt)
            response = call_llm(...)
            e.set_output(response, tokens=1234, cost=0.05)
    """
    cfg = get_config()
    active_trace = get_current_trace()

    # 不在 trace 中: 静默跳过 (不记录, 也不报错)
    # 设计选择: 与 OpenTelemetry 一致——没有 parent context 时不创建无意义的 root span
    if active_trace is None:
        # 返回一个空 proxy，业务代码不会被打扰
        yield _NullEventProxy()
        return

    # 创建 span
    parent_span = get_current_span()
    span = Span(
        parent_id=parent_span.span.span_id if parent_span else None,
        trace_id=active_trace.trace.trace_id,
    )

    # 创建初始 event
    ev = Event(
        span_id=span.span_id,
        parent_id=span.parent_id,
        trace_id=span.trace_id,
        event_type=event_type,
        name=name,
        **kwargs,
    )

    active_span = ActiveSpan(span=span, event=ev, start_time=ev.start_time)
    span_token = _push_span(active_span)

    proxy = _EventProxy(ev, active_trace)

    try:
        yield proxy
        ev.finish(EventStatus.OK)
    except Exception as e:
        ev.finish(EventStatus.ERROR)
        ev.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        # Loop detection (reasoning 事件)
        if ev.event_type == EventType.REASONING and ev.input:
            sig = str(ev.input)[:200]
            count = _check_loop(ev.trace_id, sig)
            if count >= cfg.loop_detection_threshold:
                ev.metadata["loop_detected"] = True
                ev.metadata["loop_count"] = count
                # 添加 loop warning 事件
                warn = Event(
                    trace_id=ev.trace_id,
                    parent_id=ev.parent_id,
                    event_type=EventType.ERROR,
                    name="vibetrace.loop_detected",
                    status=EventStatus.ERROR,
                    metadata={"signature": sig, "count": count},
                )
                active_trace.add_event(warn)
                _get_storage().save_event(warn)
                print(f"[vibetrace] ⚠️  Loop detected in trace {ev.trace_id[:8]}: same reasoning repeated {count}x")

        active_trace.add_event(ev)
        try:
            _get_storage().save_event(ev)
        except Exception as e:
            print(f"[vibetrace] save event failed: {e}")

        _pop_span()


class _EventProxy:
    """
    `with event(...) as e:` 中的 `e` 代理。
    """

    def __init__(self, event: Event, active_trace: ActiveTrace):
        self._event = event
        self._trace = active_trace

    @property
    def event_id(self) -> str:
        return self._event.event_id

    @property
    def span_id(self) -> str:
        return self._event.span_id

    def set_input(self, value: Any) -> None:
        cfg = get_config()
        self._event.input = value if cfg.capture_prompts else _redact(value, cfg.redact_keys)

    def set_output(self, value: Any, **kwargs) -> None:
        """设置输出 + 可选附加字段 (tokens, cost_usd 等)。"""
        cfg = get_config()
        self._event.output = value if cfg.capture_responses else _redact(value, cfg.redact_keys)
        for k, v in kwargs.items():
            if hasattr(self._event, k):
                setattr(self._event, k, v)

    def set_tokens(self, prompt: int = 0, completion: int = 0) -> None:
        self._event.prompt_tokens = prompt
        self._event.completion_tokens = completion
        self._event.total_tokens = prompt + completion

    def set_cost(self, cost_usd: float) -> None:
        self._event.cost_usd = cost_usd

    def set_error(self, error: str) -> None:
        self._event.status = EventStatus.ERROR
        self._event.error = error

    def add_metadata(self, key: str, value: Any) -> None:
        self._event.metadata[key] = value

    def add_tag(self, tag: str) -> None:
        if tag not in self._event.tags:
            self._event.tags.append(tag)


class _NullEventProxy:
    """
    当 event() 在 trace 外调用时返回的空代理。
    所有方法都是 no-op,业务代码不会被打扰。
    """

    @property
    def event_id(self) -> str:
        return ""

    @property
    def span_id(self) -> str:
        return ""

    def set_input(self, value: Any) -> None: pass
    def set_output(self, value: Any, **kwargs) -> None: pass
    def set_tokens(self, prompt: int = 0, completion: int = 0) -> None: pass
    def set_cost(self, cost_usd: float) -> None: pass
    def set_error(self, error: str) -> None: pass
    def add_metadata(self, key: str, value: Any) -> None: pass
    def add_tag(self, tag: str) -> None: pass


def record_event(
    event_type: EventType,
    name: str,
    input: Any = None,
    output: Any = None,
    **kwargs,
) -> Optional[Event]:
    """
    手动记录一个事件 (不在 context manager 中)。

    用法:
        record_event(EventType.LLM_CALL, "claude-call",
                     input=prompt, output=response, model="claude-opus-4-8", total_tokens=1234)
    """
    active = get_current_trace()
    if active is None:
        # 无 trace 上下文: 静默返回 None
        return None

    parent_span = get_current_span()
    ev = Event(
        parent_id=parent_span.span.span_id if parent_span else None,
        trace_id=active.trace.trace_id,
        event_type=event_type,
        name=name,
        input=input,
        output=output,
        **kwargs,
    )
    if ev.end_time is None:
        ev.finish()
    active.add_event(ev)
    _get_storage().save_event(ev)
    return ev


def trace_agent(
    name: Optional[str] = None,
    vibe: str = "",
    capture_args: bool = True,
    capture_result: bool = True,
):
    """
    装饰器: 给函数自动添加 trace。

    用法:
        @trace_agent(name="my-coder", vibe="minimalist and calm")
        def my_agent(task: str) -> str:
            ...
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        actual_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # 捕获输入
            fn_input = None
            if capture_args:
                try:
                    fn_input = {
                        "args": [repr(a)[:500] for a in args],
                        "kwargs": {k: repr(v)[:500] for k, v in kwargs.items()},
                    }
                except Exception:
                    fn_input = "<unrepresentable>"

            with trace(actual_name, vibe=vibe, input=fn_input) as t:
                try:
                    result = func(*args, **kwargs)
                    if capture_result:
                        try:
                            t.set_output(repr(result)[:2000])
                        except Exception:
                            t.set_output("<unrepresentable>")
                    return result
                except Exception as e:
                    t.set_metadata("exception", f"{type(e).__name__}: {e}")
                    raise

        return wrapper

    return decorator


# === Utilities ===

def _redact(value: Any, keys: list) -> Any:
    """递归地 redact 敏感 key。"""
    if not keys:
        return value
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in [rk.lower() for rk in keys] else _redact(v, keys))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(v, keys) for v in value)
    return value


def _maybe_run_analyst(trace_obj: Trace, events: list) -> None:
    """运行 analyst (MVP: 仅在有 anthropic key 时尝试)。"""
    try:
        from vibetrace.analyst import run_analyst
        run_analyst(trace_obj, events)
    except Exception as e:
        # Analyst 是 best-effort，不能让它的失败影响业务
        pass
