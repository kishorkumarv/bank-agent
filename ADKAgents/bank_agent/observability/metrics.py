"""Thread-safe in-memory observability metrics store.

Tracks LLM calls (tokens, cost, latency, prompt/response previews) and tool
invocations (counts, durations).  Supports per-session, per-turn, and
cumulative cost aggregation controlled by ``config.COST_GRANULARITY``.
"""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .config import CostGranularity, COST_GRANULARITY


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LlmCallRecord:
    timestamp: float
    session_id: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    agent_name: str = "bank_agent"
    prompt_preview: str | None = None
    response_preview: str | None = None


@dataclass
class ToolCallRecord:
    timestamp: float
    tool_name: str
    duration_ms: float
    success: bool
    error: str | None = None


@dataclass
class _SessionBucket:
    """Aggregated stats for a single session."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0
    latency_ms_values: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ObservabilityStore:
    """Central, thread-safe metrics store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._llm_calls: list[LlmCallRecord] = []
        self._tool_calls: list[ToolCallRecord] = []
        self._sessions: dict[str, _SessionBucket] = {}

    # -- recording ----------------------------------------------------------

    def record_llm_call(self, rec: LlmCallRecord) -> None:
        with self._lock:
            self._llm_calls.append(rec)
            bucket = self._sessions.setdefault(rec.session_id, _SessionBucket())
            bucket.input_tokens += rec.input_tokens
            bucket.output_tokens += rec.output_tokens
            bucket.total_tokens += rec.total_tokens
            bucket.cost_usd += rec.cost_usd
            bucket.call_count += 1
            bucket.latency_ms_values.append(rec.latency_ms)

    def record_tool_call(self, rec: ToolCallRecord) -> None:
        with self._lock:
            self._tool_calls.append(rec)

    # -- queries ------------------------------------------------------------

    def get_summary(self, granularity: CostGranularity | None = None) -> dict[str, Any]:
        """Return aggregated stats.

        *granularity* overrides the env-configured default.
        """
        gran = granularity or COST_GRANULARITY
        with self._lock:
            all_latencies = [r.latency_ms for r in self._llm_calls]
            total_input = sum(r.input_tokens for r in self._llm_calls)
            total_output = sum(r.output_tokens for r in self._llm_calls)
            total_tokens = total_input + total_output
            total_cost = sum(r.cost_usd for r in self._llm_calls)
            total_calls = len(self._llm_calls)

            # Build cost breakdown by granularity
            if gran == CostGranularity.CUMULATIVE:
                cost_breakdown = {
                    "mode": "cumulative",
                    "total_cost_usd": round(total_cost, 8),
                    "total_calls": total_calls,
                }
            elif gran == CostGranularity.TURN:
                turns = [
                    {
                        "timestamp": r.timestamp,
                        "session_id": r.session_id,
                        "cost_usd": round(r.cost_usd, 8),
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                    }
                    for r in self._llm_calls
                ]
                cost_breakdown = {"mode": "turn", "turns": turns}
            else:  # SESSION (default)
                sessions = {
                    sid: {
                        "cost_usd": round(b.cost_usd, 8),
                        "input_tokens": b.input_tokens,
                        "output_tokens": b.output_tokens,
                        "total_tokens": b.total_tokens,
                        "call_count": b.call_count,
                        "avg_latency_ms": (
                            round(statistics.mean(b.latency_ms_values), 2)
                            if b.latency_ms_values
                            else 0
                        ),
                    }
                    for sid, b in self._sessions.items()
                }
                cost_breakdown = {"mode": "session", "sessions": sessions}

            return {
                "total_llm_calls": total_calls,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 8),
                "avg_latency_ms": (
                    round(statistics.mean(all_latencies), 2) if all_latencies else 0
                ),
                "p50_latency_ms": (
                    round(statistics.median(all_latencies), 2) if all_latencies else 0
                ),
                "p95_latency_ms": (
                    round(
                        sorted(all_latencies)[int(len(all_latencies) * 0.95)]
                        if all_latencies
                        else 0,
                        2,
                    )
                ),
                "cost_breakdown": cost_breakdown,
            }

    def get_traces(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return most recent LLM call records (newest first)."""
        with self._lock:
            records = list(reversed(self._llm_calls[-limit:]))
        return [
            {
                "timestamp": r.timestamp,
                "session_id": r.session_id,
                "model": r.model,
                "agent_name": r.agent_name,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "cost_usd": round(r.cost_usd, 8),
                "latency_ms": round(r.latency_ms, 2),
                "prompt_preview": r.prompt_preview,
                "response_preview": r.response_preview,
            }
            for r in records
        ]

    def get_tool_stats(self) -> dict[str, Any]:
        """Return per-tool aggregated stats."""
        with self._lock:
            by_tool: dict[str, list[ToolCallRecord]] = {}
            for rec in self._tool_calls:
                by_tool.setdefault(rec.tool_name, []).append(rec)

        result: dict[str, Any] = {}
        for name, records in by_tool.items():
            durations = [r.duration_ms for r in records]
            successes = sum(1 for r in records if r.success)
            result[name] = {
                "call_count": len(records),
                "success_count": successes,
                "error_count": len(records) - successes,
                "avg_duration_ms": round(statistics.mean(durations), 2) if durations else 0,
                "p50_duration_ms": round(statistics.median(durations), 2) if durations else 0,
                "p95_duration_ms": (
                    round(sorted(durations)[int(len(durations) * 0.95)], 2)
                    if durations
                    else 0
                ),
            }
        return {"total_tool_calls": sum(len(v) for v in by_tool.values()), "tools": result}

    def reset(self) -> None:
        """Clear all recorded data."""
        with self._lock:
            self._llm_calls.clear()
            self._tool_calls.clear()
            self._sessions.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

store = ObservabilityStore()
