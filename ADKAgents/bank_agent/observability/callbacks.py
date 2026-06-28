"""ADK model callbacks for observability.

Implements ``before_model_callback`` and ``after_model_callback`` to capture
LLM inputs/outputs, token usage, latency, and cost.  Records are pushed to
the in-memory :pymod:`metrics` store and, when OpenTelemetry is configured,
emitted as span attributes.

.. important::
   ADK resolves callback parameters **by name** — do **not** rename
   ``callback_context`` or ``llm_response`` / ``llm_request``.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse

from .config import LOG_LLM_CONTENT, get_pricing
from .metrics import LlmCallRecord, store

try:
    from opentelemetry import trace as otel_trace
    _tracer = otel_trace.get_tracer("bank_agent.observability")
except ImportError:
    _tracer = None  # type: ignore[assignment]

logger = logging.getLogger("bank_agent.observability")

# We stash the start timestamp on callback_context.state under this key so
# we can compute wall-clock latency in the after-callback.
_START_KEY = "_obs_llm_start_ns"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_last_user_text(llm_request: LlmRequest) -> str:
    """Best-effort extraction of the most recent user message text."""
    try:
        if llm_request.contents:
            last = llm_request.contents[-1]
            if hasattr(last, "parts") and last.parts:
                texts = [p.text for p in last.parts if hasattr(p, "text") and p.text]
                return " ".join(texts)[:500]  # cap preview length
    except Exception:
        pass
    return ""


def _extract_response_text(llm_response: LlmResponse) -> str:
    """Best-effort extraction of the model response text."""
    try:
        if llm_response.content and llm_response.content.parts:
            texts = [
                p.text
                for p in llm_response.content.parts
                if hasattr(p, "text") and p.text
            ]
            return " ".join(texts)[:500]
    except Exception:
        pass
    return ""


def _session_id_from_ctx(callback_context: CallbackContext) -> str:
    """Extract a session identifier from the callback context."""
    try:
        # CallbackContext exposes a .session property that returns the Session object
        session = callback_context.session
        if session is not None:
            return str(session.id or "unknown")
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Stamp the start time and snapshot the prompt for the after-callback."""
    callback_context.state[_START_KEY] = time.perf_counter_ns()

    # Snapshot the latest user text so the after-callback can log it.
    if LOG_LLM_CONTENT:
        callback_context.state["_obs_last_prompt"] = _extract_last_user_text(llm_request)

    return None  # let the request proceed unmodified


def after_model_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """Record token usage, cost, latency, and optionally prompt/response content."""

    # 1. Latency -----------------------------------------------------------
    start_ns = callback_context.state.get(_START_KEY, None)
    if start_ns is not None:
        latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
    else:
        latency_ms = 0.0

    # 2. Token usage -------------------------------------------------------
    usage = getattr(llm_response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    total_tokens = input_tokens + output_tokens

    # 3. Cost --------------------------------------------------------------
    agent_name = getattr(callback_context, "agent_name", None)
    if not agent_name:
        agent_name = getattr(getattr(callback_context, "agent", None), "name", "bank_agent") or "bank_agent"

    model_name = getattr(
        getattr(callback_context, "agent", None), "model", "gemini-2.5-flash"
    ) or "gemini-2.5-flash"
    inp_price, out_price = get_pricing(model_name)
    cost_usd = (input_tokens * inp_price + output_tokens * out_price) / 1_000_000

    # 4. Content previews --------------------------------------------------
    prompt_preview: str | None = None
    response_preview: str | None = None
    if LOG_LLM_CONTENT:
        # We don't have llm_request in the after callback — reconstruct from context
        prompt_preview = callback_context.state.get("_obs_last_prompt", None)
        response_preview = _extract_response_text(llm_response)

    # 5. Session ID --------------------------------------------------------
    session_id = _session_id_from_ctx(callback_context)

    # 6. Record ------------------------------------------------------------
    rec = LlmCallRecord(
        timestamp=time.time(),
        session_id=session_id,
        model=model_name,
        agent_name=agent_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        prompt_preview=prompt_preview,
        response_preview=response_preview,
    )
    store.record_llm_call(rec)

    # 7. Log ---------------------------------------------------------------
    logger.info(
        "LLM call: agent=%s model=%s in=%d out=%d total=%d cost=$%.6f latency=%.1fms session=%s",
        agent_name, model_name, input_tokens, output_tokens, total_tokens, cost_usd, latency_ms, session_id,
    )

    # 8. OTEL span attributes (if tracer is available) ---------------------
    if _tracer is not None:
        span = otel_trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("llm.session_id", session_id)
            span.set_attribute("llm.agent_name", agent_name)
            span.set_attribute("llm.model", model_name)
            span.set_attribute("llm.input_tokens", input_tokens)
            span.set_attribute("llm.output_tokens", output_tokens)
            span.set_attribute("llm.total_tokens", total_tokens)
            span.set_attribute("llm.cost_usd", cost_usd)
            span.set_attribute("llm.latency_ms", latency_ms)

    return None  # let the response proceed unmodified
