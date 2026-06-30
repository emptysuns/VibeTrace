"""
Context propagation - VibeTrace 的"魔法"层

使用 Python contextvars 自动在调用栈中传播 trace context。

为什么用 contextvars？
1. 嵌套调用自动处理 (agent -> llm -> tool 都有正确的 parent_id)
2. 异步/并发安全 (asyncio task 之间不会污染)
3. 用户代码零侵入 (不需要手动传 trace_id)

这是 OpenTelemetry / LangSmith 用的核心技术。
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Optional, List

from vibetrace.core.events import Trace, Event, Span, EventType, EventStatus


# === Context Variables ===
# 这些是 VibeTrace 的"内部状态"，通过 contextvars 在调用栈中自动传播。

_current_trace: contextvars.ContextVar[Optional["ActiveTrace"]] = contextvars.ContextVar(
    "vibetrace_current_trace", default=None
)

_current_span_stack: contextvars.ContextVar[List["ActiveSpan"]] = contextvars.ContextVar(
    "vibetrace_span_stack", default=[]
)


@dataclass
class VibeTraceConfig:
    """
    全局配置。

    用户通过 `vibetrace.configure(...)` 修改。
    配置变更不影响已经在运行的 trace。
    """

    # 存储后端 (默认 SQLite)
    storage_backend: str = "sqlite"
    sqlite_path: str = "./vibetrace.db"

    # 自动捕获 hooks
    auto_capture_anthropic: bool = False  # 拦截 anthropic SDK
    auto_capture_openai: bool = False

    # 行为
    capture_prompts: bool = True  # 是否记录 prompt 内容 (敏感场景可关)
    capture_responses: bool = True
    redact_keys: List[str] = field(default_factory=lambda: ["api_key", "password", "secret"])

    # Loop detection
    loop_detection_threshold: int = 3  # 相同 reasoning 重复 N 次报警

    # Analyst
    analyst_model: str = "claude-haiku-4-5-20251001"  # 默认便宜模型
    analyst_enabled: bool = True


_config: Optional[VibeTraceConfig] = None


def configure(
    storage_backend: str = "sqlite",
    sqlite_path: str = "./vibetrace.db",
    capture_prompts: bool = True,
    capture_responses: bool = True,
    **kwargs,
) -> VibeTraceConfig:
    """配置 VibeTrace 全局行为。"""
    global _config
    _config = VibeTraceConfig(
        storage_backend=storage_backend,
        sqlite_path=sqlite_path,
        capture_prompts=capture_prompts,
        capture_responses=capture_responses,
        **kwargs,
    )
    return _config


def get_config() -> VibeTraceConfig:
    """获取当前配置。第一次调用时初始化默认配置。"""
    global _config
    if _config is None:
        _config = VibeTraceConfig()
    return _config


# === Active Objects ===
# 这些是 trace 期间"活跃"的对象，存储在 context 中。
# 用户代码不直接用，但通过 trace/event context manager 操作。

@dataclass
class ActiveTrace:
    """当前活跃的 trace。包含 Trace 对象和 event 累积器。"""

    trace: Trace
    events: List[Event] = field(default_factory=list)
    # 写完后调的回调（用于持久化、analyst 等）
    on_finish: Optional[object] = None  # Callable[[Trace, List[Event]], None]

    def add_event(self, event: Event) -> None:
        self.events.append(event)

    def update_stats(self) -> None:
        """从 events 聚合统计。finish 时调用。"""
        t = self.trace
        t.total_events = len(self.events)
        t.total_llm_calls = sum(1 for e in self.events if e.event_type == EventType.LLM_CALL)
        t.total_tool_calls = sum(1 for e in self.events if e.event_type == EventType.TOOL_CALL)
        t.total_tokens = sum(e.total_tokens or 0 for e in self.events)
        t.total_cost_usd = sum(e.cost_usd or 0.0 for e in self.events)
        t.error_count = sum(1 for e in self.events if e.status == EventStatus.ERROR)


@dataclass
class ActiveSpan:
    """当前活跃的 span。用于 event context manager 内部。"""

    span: Span
    event: Event  # 正在构建中的 event
    start_time: float

    def finish(self, status: EventStatus = EventStatus.OK) -> Event:
        self.event.finish(status)
        return self.event


# === Context accessors (供 tracer 使用) ===

def get_current_trace() -> Optional[ActiveTrace]:
    return _current_trace.get()


def get_current_span() -> Optional[ActiveSpan]:
    stack = _current_span_stack.get()
    return stack[-1] if stack else None


def _set_current_trace(at: Optional[ActiveTrace]):
    return _current_trace.set(at)


def _push_span(span: ActiveSpan):
    stack = list(_current_span_stack.get())
    stack.append(span)
    return _current_span_stack.set(stack)


def _pop_span() -> Optional[ActiveSpan]:
    stack = list(_current_span_stack.get())
    if not stack:
        return None
    span = stack.pop()
    _current_span_stack.set(stack)
    return span


def _reset_current_trace(token):
    _current_trace.reset(token)
