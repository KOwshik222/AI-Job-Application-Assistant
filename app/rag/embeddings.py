"""Embedding provider — OpenAI in production, local fake embeddings in demo mode."""

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.config import get_settings

settings = get_settings()


def is_demo_mode() -> bool:
    return settings.is_demo_mode


def get_embeddings() -> Embeddings:
    if is_demo_mode():
        from langchain_community.embeddings import FakeEmbeddings

        return FakeEmbeddings(size=384)
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.openai_api_key,
    )
