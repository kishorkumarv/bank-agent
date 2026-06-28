"""``@traced_tool`` decorator for automatic tool-call observability.

Wraps any ADK tool function to measure execution time and record the call
in the :pymod:`metrics` store.  An OpenTelemetry child span is created when
the tracer is available.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from .metrics import ToolCallRecord, store

try:
    from opentelemetry import trace as otel_trace
    _tracer = otel_trace.get_tracer("bank_agent.observability.tools")
except ImportError:
    _tracer = None  # type: ignore[assignment]

logger = logging.getLogger("bank_agent.observability.tools")


def traced_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that records tool invocation duration and success/failure.

    Usage::

        from bank_agent.observability.tool_tracer import traced_tool

        @traced_tool
        def my_tool(query: str) -> str:
            ...

    The decorator preserves the original function's signature, docstring,
    and type hints so ADK can still introspect the tool correctly.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tool_name = fn.__name__
        start_ns = time.perf_counter_ns()
        error_msg: str | None = None
        success = True

        # Optional OTEL span
        span_ctx = (
            _tracer.start_as_current_span(f"tool:{tool_name}")
            if _tracer is not None
            else _noop_ctx()
        )

        try:
            with span_ctx as span:
                result = fn(*args, **kwargs)
                if span is not None and hasattr(span, "set_attribute"):
                    span.set_attribute("tool.name", tool_name)
                    span.set_attribute("tool.success", True)
                return result
        except Exception as exc:
            success = False
            error_msg = str(exc)
            if _tracer is not None:
                current_span = otel_trace.get_current_span()
                if current_span and current_span.is_recording():
                    current_span.set_attribute("tool.success", False)
                    current_span.set_attribute("tool.error", error_msg)
            raise
        finally:
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            rec = ToolCallRecord(
                timestamp=time.time(),
                tool_name=tool_name,
                duration_ms=duration_ms,
                success=success,
                error=error_msg,
            )
            store.record_tool_call(rec)
            logger.info(
                "Tool call: name=%s duration=%.1fms success=%s",
                tool_name, duration_ms, success,
            )

    return wrapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _noop_ctx:
    """Minimal no-op context manager when OTEL isn't available."""
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: Any) -> None:
        pass
