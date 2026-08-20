"""Tests for strict LLM provider enforcement.

Verifies:
- Gemini selected → only Gemini
- Gemini failure → LLM_PROVIDER_ERROR  
- OpenAI selected → only OpenAI
- OpenAI failure → LLM_PROVIDER_ERROR
- No cross-provider fallback
- Production does not silently enter demo mode
"""

import os
import pytest
from unittest.mock import patch


def test_gemini_missing_key_raises_error():
    """When LLM_PROVIDER=gemini but no key → LLMProviderError, not OpenAI fallback."""
    from app.rag.llm_provider import LLMProviderError, get_llm

    with patch("app.rag.llm_provider.settings") as mock_settings:
        mock_settings.llm_provider = "gemini"
        mock_settings.active_gemini_key = ""
        mock_settings.openai_api_key = "sk-test-openai-key"  # Available but must NOT be used

        with pytest.raises(LLMProviderError) as exc_info:
            get_llm()

        assert exc_info.value.provider == "gemini"
        assert "not configured" in exc_info.value.reason.lower()
        assert exc_info.value.detail["status"] == "LLM_PROVIDER_ERROR"


def test_openai_missing_key_raises_error():
    """When LLM_PROVIDER=openai but no key → LLMProviderError, not Gemini fallback."""
    from app.rag.llm_provider import LLMProviderError, get_llm

    with patch("app.rag.llm_provider.settings") as mock_settings:
        mock_settings.llm_provider = "openai"
        mock_settings.openai_api_key = ""
        mock_settings.active_gemini_key = "gemini-key-available"  # Available but must NOT be used

        with pytest.raises(LLMProviderError) as exc_info:
            get_llm()

        assert exc_info.value.provider == "openai"
        assert "not configured" in exc_info.value.reason.lower()


def test_unknown_provider_raises_error():
    """Unknown LLM_PROVIDER → LLMProviderError."""
    from app.rag.llm_provider import LLMProviderError, get_llm

    with patch("app.rag.llm_provider.settings") as mock_settings:
        mock_settings.llm_provider = "anthropic"

        with pytest.raises(LLMProviderError) as exc_info:
            get_llm()

        assert "unknown" in exc_info.value.reason.lower()


def test_no_cross_provider_fallback_gemini_to_openai():
    """Even if Gemini init fails AND OpenAI key exists, must NOT fall back.
    
    We verify this by checking: when provider=gemini and gemini key exists but
    initialization raises, an LLMProviderError is raised (not an OpenAI model).
    """
    from app.rag.llm_provider import LLMProviderError, get_llm
    import sys

    with patch("app.rag.llm_provider.settings") as mock_settings:
        mock_settings.llm_provider = "gemini"
        mock_settings.active_gemini_key = "fake-key"
        mock_settings.gemini_chat_model = "gemini-2.0-flash"
        mock_settings.openai_api_key = "sk-test-openai"

        # Make the langchain_google_genai module raise on ChatGoogleGenerativeAI init
        fake_module = type(sys)("langchain_google_genai")

        class FailingChat:
            def __init__(self, *args, **kwargs):
                raise Exception("Gemini init error")

        fake_module.ChatGoogleGenerativeAI = FailingChat
        saved = sys.modules.get("langchain_google_genai")

        try:
            sys.modules["langchain_google_genai"] = fake_module
            with pytest.raises(LLMProviderError) as exc_info:
                get_llm()
            assert exc_info.value.provider == "gemini"
            # Must NOT have fallen back to OpenAI
            assert "openai" not in str(exc_info.value.reason).lower()
        finally:
            if saved is not None:
                sys.modules["langchain_google_genai"] = saved
            elif "langchain_google_genai" in sys.modules:
                del sys.modules["langchain_google_genai"]


def test_demo_mode_only_explicit():
    """DEMO_MODE must be explicitly set, not derived from missing keys."""
    from app.config import Settings

    # No API keys, DEMO_MODE not set → is_demo_mode should be False
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="",
        google_api_key="",
        openai_api_key="",
        demo_mode=False,
    )
    assert settings.is_demo_mode is False

    # DEMO_MODE=true → is_demo_mode should be True
    settings_demo = Settings(
        llm_provider="gemini",
        gemini_api_key="",
        demo_mode=True,
    )
    assert settings_demo.is_demo_mode is True


def test_embeddings_no_silent_fake_in_production():
    """Production mode must NOT silently use FakeEmbeddings."""
    from app.rag.llm_provider import LLMProviderError, get_embeddings

    with patch("app.rag.llm_provider.settings") as mock_settings:
        mock_settings.is_demo_mode = False
        mock_settings.llm_provider = "gemini"
        mock_settings.active_gemini_key = ""

        with pytest.raises(LLMProviderError):
            get_embeddings()


def test_embeddings_fake_only_in_demo_mode():
    """FakeEmbeddings should only be used when DEMO_MODE=true."""
    from app.rag.llm_provider import get_embeddings

    with patch("app.rag.llm_provider.settings") as mock_settings:
        mock_settings.is_demo_mode = True

        embeddings = get_embeddings()
        assert "Fake" in type(embeddings).__name__
