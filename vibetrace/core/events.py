"""
核心事件模型 - VibeTrace 的"数据类型"层

设计哲学：
- Trace = 一次完整 agent 运行 (root container)
- Span = 一次逻辑步骤 (LLM call, tool call, decision)
- Event = span 的不可变记录 (写入 storage 的单元)

所有时间都用 time.time() 浮点秒。
所有 ID 用 uuid4 字符串。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class EventType(str, Enum):
    """事件的语义类型。Dashboard 用它来着色和分组。"""

    TRACE_START = "trace.start"
    TRACE_END = "trace.end"
    LLM_CALL = "llm.call"
    TOOL_CALL = "tool.call"
    REASONING = "reasoning"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    DECISION = "decision"
    ERROR = "error"
    RETRY = "retry"
    HUMAN_INPUT = "human.input"


class EventStatus(str, Enum):
    """事件执行状态。"""

    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Event:
    """
    VibeTrace 的不可变事件记录。

    每个 Event 代表 trace 中的一步：一次 LLM 调用、一次工具调用、
    一次 reasoning、一次错误等。所有 Event 通过 tracer 写入 storage。

    字段按"必须"和"可选"分组，保持 dict 序列化的紧凑性。
    """

    # === Identity ===
    event_id: str = field(default_factory=_new_id)
    trace_id: str = ""
    parent_id: Optional[str] = None
    span_id: str = field(default_factory=_new_id)

    # === Type & Status ===
    event_type: EventType = EventType.LLM_CALL
    name: str = ""
    status: EventStatus = EventStatus.OK

    # === Timing ===
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None

    # === Payload (类型相关) ===
    input: Any = None
    output: Any = None
    error: Optional[str] = None

    # === LLM specific ===
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None

    # === Tool specific ===
    tool_name: Optional[str] = None

    # === Metadata (自由扩展) ===
    metadata: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)

    def finish(self, status: EventStatus = EventStatus.OK) -> None:
        """标记事件结束。设置 end_time 和 duration。
        如果已经通过 set_error() 标记为 ERROR, 保留 ERROR 状态。
        """
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        # 关键: 如果用户已经 set_error(), 不要覆盖成 OK
        if not (self.status == EventStatus.ERROR and self.error):
            self.status = status

    def to_dict(self) -> dict:
        """序列化为 dict。enum 转字符串，None 字段保留以便 dashboard 区分。"""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        """从 dict 反序列化（用于从 storage 读取）。"""
        d = dict(d)
        d["event_type"] = EventType(d["event_type"])
        d["status"] = EventStatus(d["status"])
        return cls(**d)


@dataclass
class Trace:
    """
    一次完整的 agent 运行。

    包含：根 metadata、input/output、vibe、所有 event 的引用。
    Trace 本身也是一个 root Span。
    """

    trace_id: str = field(default_factory=_new_id)
    name: str = ""
    vibe: str = ""  # 原始 vibe 描述，用于 vibe deviation 检测
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None

    input: Any = None
    output: Any = None

    status: EventStatus = EventStatus.OK
    error: Optional[str] = None

    # 统计 (在 finish 时计算)
    total_events: int = 0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error_count: int = 0

    # 自由 metadata
    metadata: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)

    def finish(self, status: EventStatus = EventStatus.OK) -> None:
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Trace":
        d = dict(d)
        d["status"] = EventStatus(d["status"])
        return cls(**d)


@dataclass
class Span:
    """
    Span 是 Event 的"包装器"。

    Span 持有 start_time 和状态，调用 finish() 时计算 duration。
    区别于 Event：Span 是 in-memory 的，正在进行的；
    Event 是 finalized 的，可序列化的。
    """

    span_id: str = field(default_factory=_new_id)
    parent_id: Optional[str] = None
    trace_id: str = ""

    def to_event(
        self,
        event_type: EventType,
        name: str,
        start_time: float,
        end_time: float,
        **kwargs,
    ) -> Event:
        """把 span 转化为 final Event。"""
        return Event(
            span_id=self.span_id,
            parent_id=self.parent_id,
            trace_id=self.trace_id,
            event_type=event_type,
            name=name,
            start_time=start_time,
            end_time=end_time,
            duration_ms=(end_time - start_time) * 1000,
            **kwargs,
        )


# === Convenience aliases for typed events ===

LLMCall = Event  # event_type = LLM_CALL
ToolCall = Event  # event_type = TOOL_CALL
