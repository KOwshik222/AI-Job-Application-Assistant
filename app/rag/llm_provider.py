"""LLM and Embeddings provider abstraction factory."""

import logging
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """Return configured Chat LLM (Gemini, OpenAI, or raises/falls back)."""
    provider = settings.llm_provider.lower()

    if provider == "gemini" and settings.active_gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=settings.gemini_chat_model,
                google_api_key=settings.active_gemini_key,
                temperature=temperature,
            )
        except Exception as e:
            logger.error("Failed to initialize ChatGoogleGenerativeAI: %s", e)

    if (provider == "openai" or not settings.active_gemini_key) and settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=settings.chat_model,
                openai_api_key=settings.openai_api_key,
                temperature=temperature,
            )
        except Exception as e:
            logger.error("Failed to initialize ChatOpenAI: %s", e)

    # Fallback to OpenAI if key exists
    if settings.openai_api_key:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.chat_model,
            openai_api_key=settings.openai_api_key,
            temperature=temperature,
        )

    # Fallback to Gemini if key exists
    if settings.active_gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_chat_model,
            google_api_key=settings.active_gemini_key,
            temperature=temperature,
        )

    raise ValueError("No active LLM provider configured with valid API keys.")


def get_embeddings() -> Embeddings:
    """Return configured Embedding model (Google, OpenAI, or Fake for demo mode)."""
    if settings.is_demo_mode:
        from langchain_community.embeddings import FakeEmbeddings
        return FakeEmbeddings(size=384)

    provider = settings.llm_provider.lower()

    if provider == "gemini" and settings.active_gemini_key:
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            return GoogleGenerativeAIEmbeddings(
                model=settings.gemini_embedding_model,
                google_api_key=settings.active_gemini_key,
            )
        except Exception as e:
            logger.warning("Failed to initialize GoogleGenerativeAIEmbeddings: %s", e)

    if settings.openai_api_key:
        try:
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings(
                model=settings.embedding_model,
                openai_api_key=settings.openai_api_key,
            )
        except Exception as e:
            logger.warning("Failed to initialize OpenAIEmbeddings: %s", e)

    from langchain_community.embeddings import FakeEmbeddings
    return FakeEmbeddings(size=384)
