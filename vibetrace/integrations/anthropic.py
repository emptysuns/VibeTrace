"""
Anthropic SDK 自动追踪

一行启用:
    from vibetrace.integrations.anthropic import patch
    patch()

之后所有 anthropic.Anthropic().messages.create() 调用都会自动追踪。
"""
from __future__ import annotations

from typing import Any, Optional
import time


def patch():
    """Monkey-patch Anthropic SDK 让所有调用自动追踪。"""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic SDK not installed: pip install anthropic")

    from vibetrace.core.events import EventType, EventStatus
    from vibetrace.core.context import get_current_trace, get_current_span

    # 保存原方法
    original_create = anthropic.resources.messages.Messages.create

    def traced_create(self, *args, **kwargs):
        active = get_current_trace()
        if active is None:
            # 不在 trace 中: 直接调用，不记录
            return original_create(self, *args, **kwargs)

        # 计算 cost (claude 系列价格 per 1M tokens)
        model = kwargs.get("model", "unknown")
        prompt_tokens_est = sum(
            len(str(m.get("content", "")).split()) * 2
            for m in kwargs.get("messages", [])
        )

        from vibetrace.core.tracer import event

        with event(f"anthropic:{model}", EventType.LLM_CALL, model=model) as e:
            e.set_input(kwargs.get("messages", []))
            e.metadata["max_tokens"] = kwargs.get("max_tokens")

            try:
                response = original_create(self, *args, **kwargs)
                # 提取 usage
                usage = getattr(response, "usage", None)
                if usage:
                    e.set_tokens(
                        prompt=getattr(usage, "input_tokens", 0) or 0,
                        completion=getattr(usage, "output_tokens", 0) or 0,
                    )
                    # 估算 cost
                    cost = _estimate_anthropic_cost(
                        model,
                        getattr(usage, "input_tokens", 0) or 0,
                        getattr(usage, "output_tokens", 0) or 0,
                    )
                    e.set_cost(cost)

                # 提取 output
                content = getattr(response, "content", [])
                if content and hasattr(content[0], "text"):
                    e.set_output(content[0].text)
                else:
                    e.set_output(str(response)[:1000])
                return response
            except Exception as ex:
                e.set_error(f"{type(ex).__name__}: {ex}")
                raise

    anthropic.resources.messages.Messages.create = traced_create
    print("[vibetrace] Anthropic SDK patched ✨")


def _estimate_anthropic_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """估算 Anthropic API cost (USD)。价格 per 1M tokens."""
    # 2026 年价格表 (估算, 实际请查最新)
    prices = {
        "claude-opus-4-8": (15.0, 75.0),
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-haiku-4-5-20251001": (0.25, 1.25),
    }
    for prefix, (input_price, output_price) in prices.items():
        if model.startswith(prefix):
            return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
    return 0.0
