"""Deterministic recommendation layer with optional LLM enrichment."""

from .engine import Recommendation, RecommendationEngine
from .llm import LLMPayloadError, LLMProvider, NullLLMProvider, build_llm_payload

__all__ = [
    "LLMPayloadError",
    "LLMProvider",
    "NullLLMProvider",
    "Recommendation",
    "RecommendationEngine",
    "build_llm_payload",
]
