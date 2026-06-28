"""Observability configuration — env vars, model pricing, and cost granularity."""

import os
from enum import Enum


# ---------------------------------------------------------------------------
# Cost-tracking granularity
# ---------------------------------------------------------------------------

class CostGranularity(Enum):
    """Controls how cost is aggregated and reported."""
    SESSION = "session"       # per ADK session (default)
    TURN = "turn"             # per user→agent turn
    CUMULATIVE = "cumulative" # running total across all sessions


def _parse_granularity(raw: str) -> CostGranularity:
    try:
        return CostGranularity(raw.strip().lower())
    except ValueError:
        return CostGranularity.SESSION


# ---------------------------------------------------------------------------
# Environment knobs
# ---------------------------------------------------------------------------

TRACE_TO_CLOUD: bool = os.getenv("TRACE_TO_CLOUD", "false").lower() == "true"
LOG_LLM_CONTENT: bool = os.getenv("LOG_LLM_CONTENT", "true").lower() == "true"
COST_GRANULARITY: CostGranularity = _parse_granularity(
    os.getenv("COST_GRANULARITY", "session")
)

# Map of base model-name → (input_price_per_1m, output_price_per_1m) in USD
# Source: https://cloud.google.com/vertex-ai/generative-ai/pricing
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Gemini 3.5 / 3.1 / 3
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3-pro-preview": (2.00, 12.00),
    
    # Gemini 2.5
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro":   (1.25, 10.00),
    
    # Gemini 2.0
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-thinking": (0.10, 0.40),
    "gemini-2.0-pro": (1.25, 10.00),
    
    # Gemini 1.5
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    
    # Gemini 1.0 / Ultra / Pro
    "gemini-1.0-pro": (0.50, 1.50),
    "gemini-ultra": (2.00, 8.00),
}

# Fallback for unknown models
DEFAULT_PRICING: tuple[float, float] = (0.30, 2.50)


def _normalize_model_name(model: str) -> str:
    """Normalize Vertex AI/Gemini model name to match the pricing key."""
    if not model:
        return ""
    
    # Lowercase and strip spaces
    model = model.strip().lower()
    
    # Remove Vertex AI resource prefixes if present (e.g. "publishers/google/models/gemini-1.5-flash")
    if "/models/" in model:
        model = model.split("/models/")[-1]
    
    # Remove namespace prefix if present (e.g. "google/gemini-1.5-flash")
    if "/" in model:
        model = model.split("/")[-1]
        
    # Standardize common variations/suffixes (e.g. gemini-1.5-flash-001 -> gemini-1.5-flash)
    for base_model in MODEL_PRICING.keys():
        if model.startswith(base_model):
            return base_model
            
    return model


def get_pricing(model: str) -> tuple[float, float]:
    """Return ``(input_price_per_1m, output_price_per_1m)`` for *model*."""
    normalized = _normalize_model_name(model)
    print(f"Model: {model}, Normalized: {normalized}, Pricing: {MODEL_PRICING.get(normalized, DEFAULT_PRICING)}")
    return MODEL_PRICING.get(normalized, DEFAULT_PRICING)

