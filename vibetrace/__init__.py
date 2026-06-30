"""
VibeTrace - 让 Agent 调试从"猜"变成"看 + AI 解释"
"""

__version__ = "0.1.0"
__vibe__ = "calm, insightful, minimalist"

# 公开 API
from vibetrace.core.events import (
    Event,
    EventType,
    Trace,
    Span,
    LLMCall,
    ToolCall,
    EventStatus,
)
from vibetrace.core.tracer import trace, event, trace_agent, get_current_trace
from vibetrace.core.context import configure, get_config, VibeTraceConfig

__all__ = [
    "Event",
    "EventType",
    "Trace",
    "Span",
    "LLMCall",
    "ToolCall",
    "EventStatus",
    "trace",
    "event",
    "trace_agent",
    "get_current_trace",
    "configure",
    "get_config",
    "VibeTraceConfig",
    "__version__",
    "__vibe__",
]
