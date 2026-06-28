"""Observability package for the bank agent.

Provides:

* **LLM call tracing** — token counts, cost, latency, prompt/response content.
* **Tool call tracing** — duration, success/failure per tool.
* **OpenTelemetry integration** — local stdout or Cloud Trace / Cloud Monitoring.

Quick start::

    from bank_agent.observability import setup_observability
    setup_observability()
"""

from .callbacks import after_model_callback, before_model_callback
from .config import COST_GRANULARITY, CostGranularity, LOG_LLM_CONTENT, TRACE_TO_CLOUD
from .metrics import store
from .otel_setup import init_otel
from .tool_tracer import traced_tool


def setup_observability() -> None:
    """One-shot initialisation — call at import time (e.g. in ``agent.py``)."""
    init_otel()


__all__ = [
    "setup_observability",
    "before_model_callback",
    "after_model_callback",
    "traced_tool",
    "store",
    "TRACE_TO_CLOUD",
    "LOG_LLM_CONTENT",
    "COST_GRANULARITY",
    "CostGranularity",
]
