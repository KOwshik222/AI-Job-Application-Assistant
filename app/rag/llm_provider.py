"""LLM and Embeddings provider abstraction factory — STRICT provider enforcement."""

import logging
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMProviderError(Exception):
    """Raised when the configured LLM provider fails or is misconfigured."""

    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.reason = reason
        self.detail = {
            "status": "LLM_PROVIDER_ERROR",
            "provider": provider,
            "reason": reason,
        }
        super().__init__(f"LLM_PROVIDER_ERROR [{provider}]: {reason}")


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """Return configured Chat LLM. STRICT — never falls back to another provider.
    
    If LLM_PROVIDER=gemini → only Gemini. Failure → LLMProviderError.
    If LLM_PROVIDER=openai → only OpenAI. Failure → LLMProviderError.
    """
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        if not settings.active_gemini_key:
            raise LLMProviderError(
                provider="gemini",
                reason="GEMINI_API_KEY (or GOOGLE_API_KEY) is not configured",
            )
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=settings.gemini_chat_model,
                google_api_key=settings.active_gemini_key,
                temperature=temperature,
            )
        except Exception as e:
            logger.error("Failed to initialize ChatGoogleGenerativeAI: %s", e)
            raise LLMProviderError(
                provider="gemini",
                reason=f"Gemini initialization failed: {e}",
            ) from e

    elif provider == "openai":
        if not settings.openai_api_key:
            raise LLMProviderError(
                provider="openai",
                reason="OPENAI_API_KEY is not configured",
            )
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=settings.chat_model,
                openai_api_key=settings.openai_api_key,
                temperature=temperature,
            )
        except Exception as e:
            logger.error("Failed to initialize ChatOpenAI: %s", e)
            raise LLMProviderError(
                provider="openai",
                reason=f"OpenAI initialization failed: {e}",
            ) from e

    else:
        raise LLMProviderError(
            provider=provider,
            reason=f"Unknown LLM_PROVIDER '{provider}'. Supported: 'gemini', 'openai'",
        )


def get_embeddings() -> Embeddings:
    """Return configured Embedding model. STRICT — no silent FakeEmbeddings in production.
    
    Demo mode (DEMO_MODE=true) → FakeEmbeddings.
    Production → configured provider only, fails loudly on error.
    """
    if settings.is_demo_mode:
        from langchain_community.embeddings import FakeEmbeddings
        logger.info("DEMO_MODE: Using FakeEmbeddings (size=384)")
        return FakeEmbeddings(size=384)

    provider = settings.llm_provider.lower()

    if provider == "gemini":
        if not settings.active_gemini_key:
            raise LLMProviderError(
                provider="gemini",
                reason="GEMINI_API_KEY is not configured for embeddings",
            )
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            return GoogleGenerativeAIEmbeddings(
                model=settings.gemini_embedding_model,
                google_api_key=settings.active_gemini_key,
            )
        except Exception as e:
            logger.error("Failed to initialize GoogleGenerativeAIEmbeddings: %s", e)
            raise LLMProviderError(
                provider="gemini",
                reason=f"Gemini embeddings initialization failed: {e}",
            ) from e

    elif provider == "openai":
        if not settings.openai_api_key:
            raise LLMProviderError(
                provider="openai",
                reason="OPENAI_API_KEY is not configured for embeddings",
            )
        try:
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings(
                model=settings.embedding_model,
                openai_api_key=settings.openai_api_key,
            )
        except Exception as e:
            logger.error("Failed to initialize OpenAIEmbeddings: %s", e)
            raise LLMProviderError(
                provider="openai",
                reason=f"OpenAI embeddings initialization failed: {e}",
            ) from e

    else:
        raise LLMProviderError(
            provider=provider,
            reason=f"Unknown LLM_PROVIDER '{provider}' for embeddings",
        )
