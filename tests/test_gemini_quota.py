"""Tests for Gemini 429 quota exhaustion handling in the matcher."""

import pytest
from unittest.mock import patch, MagicMock

from app.rag.matcher import (
    _is_quota_error,
    is_quota_exhausted,
    match_job_to_resume,
    reset_quota_flag,
)
from app.schemas import JobListing, UserProfile


@pytest.fixture(autouse=True)
def reset_quota():
    """Ensure quota flag is clean before each test."""
    reset_quota_flag()
    yield
    reset_quota_flag()


def _make_job(company: str = "TestCorp", title: str = "AI Developer") -> JobListing:
    return JobListing(
        job_id="test-job-1",
        title=title,
        company=company,
        location="Hyderabad",
        description="Build AI systems using Python, ML, LLMs",
        application_url=f"https://{company.lower().replace(' ', '')}.com/apply",
        source="test",
    )


def _make_profile() -> UserProfile:
    return UserProfile(
        role="AI Developer",
        skills=["Python", "Machine Learning", "LLMs"],
        experience=1,
        locations=["Hyderabad"],
        email="test@example.com",
        full_name="Test User",
    )


class TestQuotaErrorDetection:
    """Test _is_quota_error detects various 429/quota error formats."""

    def test_detects_429_status_code(self):
        exc = Exception("HTTP 429 Too Many Requests")
        assert _is_quota_error(exc) is True

    def test_detects_resource_exhausted(self):
        exc = Exception("google.api_core.exceptions.ResourceExhausted: RESOURCE_EXHAUSTED")
        assert _is_quota_error(exc) is True

    def test_detects_quota_keyword(self):
        exc = Exception("Quota exceeded for model")
        assert _is_quota_error(exc) is True

    def test_detects_rate_limit(self):
        exc = Exception("Rate limit exceeded")
        assert _is_quota_error(exc) is True

    def test_detects_wrapped_cause_429(self):
        cause = Exception("HTTP 429")
        exc = Exception("LLM call failed")
        exc.__cause__ = cause
        assert _is_quota_error(exc) is True

    def test_non_quota_error_returns_false(self):
        exc = Exception("Network timeout connecting to server")
        assert _is_quota_error(exc) is False

    def test_generic_value_error_returns_false(self):
        exc = ValueError("Invalid input format")
        assert _is_quota_error(exc) is False


class TestQuotaFlagBehavior:
    """Test the quota flag set/reset/check lifecycle."""

    def test_initial_state_not_exhausted(self):
        assert is_quota_exhausted() is False

    @patch("app.rag.matcher.get_retriever")
    @patch("app.rag.matcher.get_resume_text", return_value="Test resume")
    @patch("app.rag.matcher.get_llm")
    @patch("app.rag.matcher.settings")
    def test_429_sets_quota_flag(self, mock_settings, mock_llm, mock_text, mock_retriever):
        """After a 429 error, the quota flag should be set."""
        mock_settings.is_demo_mode = False
        mock_retriever.return_value.invoke.return_value = []

        # Make the LLM chain raise a 429
        llm_instance = MagicMock()
        llm_instance.with_structured_output.return_value = MagicMock(
            side_effect=Exception("429 RESOURCE_EXHAUSTED: Quota exceeded")
        )
        mock_llm.return_value = llm_instance

        job = _make_job()
        profile = _make_profile()

        result = match_job_to_resume(job, "resume-1", profile)

        assert is_quota_exhausted() is True
        assert "LLM_QUOTA_EXCEEDED" in result.match_rationale
        assert result.match_score == 0

    @patch("app.rag.matcher.get_retriever")
    @patch("app.rag.matcher.get_resume_text", return_value="Test resume")
    @patch("app.rag.matcher.get_llm")
    @patch("app.rag.matcher.settings")
    def test_subsequent_calls_short_circuit(self, mock_settings, mock_llm, mock_text, mock_retriever):
        """Once quota is exhausted, subsequent calls should NOT hit the LLM."""
        mock_settings.is_demo_mode = False
        mock_retriever.return_value.invoke.return_value = []

        # First call: trigger 429
        llm_instance = MagicMock()
        chain_mock = MagicMock(side_effect=Exception("429 RESOURCE_EXHAUSTED"))
        llm_instance.with_structured_output.return_value = chain_mock
        mock_llm.return_value = llm_instance

        job1 = _make_job("Company1")
        job2 = _make_job("Company2")
        profile = _make_profile()

        # First call triggers the flag
        match_job_to_resume(job1, "resume-1", profile)
        assert is_quota_exhausted() is True

        # Reset the chain mock to verify it's NOT called again
        chain_mock.reset_mock()
        mock_llm.reset_mock()

        # Second call should short-circuit without touching LLM
        result2 = match_job_to_resume(job2, "resume-1", profile)

        assert "LLM_QUOTA_EXCEEDED" in result2.match_rationale
        assert result2.match_score == 0
        # LLM should NOT have been called for the second job
        mock_llm.assert_not_called()

    @patch("app.rag.matcher.settings")
    def test_reset_clears_flag(self, mock_settings):
        """reset_quota_flag should clear the exhaustion state."""
        from app.rag.matcher import _gemini_quota_exhausted
        import app.rag.matcher as matcher_module

        matcher_module._gemini_quota_exhausted = True
        assert is_quota_exhausted() is True

        reset_quota_flag()
        assert is_quota_exhausted() is False


class TestQuotaErrorNotMisclassified:
    """Jobs that fail due to quota are NOT treated as 0% genuine matches."""

    @patch("app.rag.matcher.get_retriever")
    @patch("app.rag.matcher.get_resume_text", return_value="Test resume")
    @patch("app.rag.matcher.get_llm")
    @patch("app.rag.matcher.settings")
    def test_quota_jobs_not_treated_as_zero_match(
        self, mock_settings, mock_llm, mock_text, mock_retriever,
    ):
        """LLM_QUOTA_EXCEEDED rationale is distinct from MATCHING_FAILED."""
        mock_settings.is_demo_mode = False
        mock_retriever.return_value.invoke.return_value = []

        llm_instance = MagicMock()
        llm_instance.with_structured_output.return_value = MagicMock(
            side_effect=Exception("429 RESOURCE_EXHAUSTED")
        )
        mock_llm.return_value = llm_instance

        result = match_job_to_resume(_make_job(), "resume-1", _make_profile())

        assert "LLM_QUOTA_EXCEEDED" in result.match_rationale
        assert "MATCHING_FAILED" not in result.match_rationale
