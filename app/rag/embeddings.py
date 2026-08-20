"""Embedding provider delegation to LLM provider factory."""

from langchain_core.embeddings import Embeddings
from app.config import get_settings
from app.rag.llm_provider import get_embeddings as factory_get_embeddings

settings = get_settings()


def is_demo_mode() -> bool:
    """Demo mode is ONLY active when explicitly set via DEMO_MODE=true."""
    return settings.is_demo_mode


def get_embeddings() -> Embeddings:
    return factory_get_embeddings()
