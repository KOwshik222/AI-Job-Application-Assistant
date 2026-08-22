"""Tests for Phase 4 & 5: Application Automation, Adapters, Verification, and Security Barriers."""

import json
import pytest

from mcp_server.tools.apply_job import (
    apply_job_tool,
    _verify_submission_success,
    CONFIRMATION_PATTERNS,
    CONFIRMATION_URL_PATTERNS,
)
from app.services.resume_storage import compute_file_hash, verify_resume_integrity


@pytest.mark.asyncio
async def test_apply_job_mock_success_with_hash(sample_pdf_path):
    expected_hash = compute_file_hash(sample_pdf_path)
    res = await apply_job_tool(
        application_url="https://boards.greenhouse.io/stripe/jobs/123",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "applicant@test.com", "full_name": "Test User"},
        company="Stripe",
        job_title="Software Engineer",
        mock_mode=True,
    )
    data = json.loads(res)
    assert data["status"] == "SUCCESS"
    assert data["company"] == "Stripe"
    assert data["job_title"] == "Software Engineer"
    assert data["resume_hash"] == expected_hash
    assert "confirmation" in data
    assert verify_resume_integrity(sample_pdf_path, data["resume_hash"])["valid"] is True


@pytest.mark.asyncio
async def test_apply_job_mock_security_barrier_login(sample_pdf_path):
    res = await apply_job_tool(
        application_url="https://careers.example.com/login/auth",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "applicant@test.com"},
        company="SecuredCorp",
        job_title="Developer",
        mock_mode=True,
    )
    data = json.loads(res)
    assert data["status"] == "MANUAL_ACTION_REQUIRED"
    assert "Login" in data["reason"] or "Authentication" in data["reason"]


@pytest.mark.asyncio
async def test_apply_job_missing_resume_rejected():
    res = await apply_job_tool(
        application_url="https://boards.greenhouse.io/test/jobs/1",
        resume_file_path="C:/non_existent_path/fake_resume.pdf",
        user_profile={"email": "applicant@test.com"},
        mock_mode=True,
    )
    data = json.loads(res)
    assert data["status"] == "FAILED"
    assert "not found" in data["reason"].lower()


@pytest.mark.asyncio
async def test_apply_job_invalid_url_rejected(sample_pdf_path):
    res = await apply_job_tool(
        application_url="not-valid-url",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "applicant@test.com"},
        mock_mode=True,
    )
    data = json.loads(res)
    assert data["status"] == "FAILED"
    assert "Invalid" in data["reason"]


# --- Submission verification pattern tests ---


class TestConfirmationPatterns:
    """Verify that CONFIRMATION_PATTERNS cover key ATS confirmation messages."""

    def test_thank_you_pattern(self):
        import re
        text = "Thank you for applying to our company"
        assert any(re.search(p, text, re.IGNORECASE) for p in CONFIRMATION_PATTERNS)

    def test_application_submitted_pattern(self):
        import re
        text = "Your application has been submitted successfully"
        assert any(re.search(p, text, re.IGNORECASE) for p in CONFIRMATION_PATTERNS)

    def test_application_received_pattern(self):
        import re
        text = "We have received your application"
        assert any(re.search(p, text, re.IGNORECASE) for p in CONFIRMATION_PATTERNS)

    def test_application_complete_pattern(self):
        import re
        text = "Application Complete - you will hear from us soon"
        assert any(re.search(p, text, re.IGNORECASE) for p in CONFIRMATION_PATTERNS)

    def test_confirmation_id_pattern(self):
        import re
        text = "Confirmation ID: APP-2026-XYZ123"
        assert any(re.search(p, text, re.IGNORECASE) for p in CONFIRMATION_PATTERNS)

    def test_random_page_not_matched(self):
        import re
        text = "Welcome to our careers page. Browse open positions below."
        assert not any(re.search(p, text, re.IGNORECASE) for p in CONFIRMATION_PATTERNS)


class TestConfirmationURLPatterns:
    """Verify URL patterns cover key ATS confirmation URLs."""

    def test_thank_you_url(self):
        import re
        url = "https://careers.example.com/thank-you"
        assert any(re.search(p, url) for p in CONFIRMATION_URL_PATTERNS)

    def test_application_complete_url(self):
        import re
        url = "https://jobs.lever.co/company/apply/complete"
        assert any(re.search(p, url) for p in CONFIRMATION_URL_PATTERNS)

    def test_submitted_url(self):
        import re
        url = "https://boards.greenhouse.io/submitted"
        assert any(re.search(p, url) for p in CONFIRMATION_URL_PATTERNS)

    def test_job_listing_url_not_matched(self):
        import re
        url = "https://careers.example.com/jobs/senior-engineer"
        assert not any(re.search(p, url) for p in CONFIRMATION_URL_PATTERNS)


class TestMockBarrierStatus:
    """Mock-mode barrier keywords correctly return MANUAL_ACTION_REQUIRED."""

    @pytest.mark.asyncio
    async def test_captcha_url_returns_manual(self, sample_pdf_path):
        res = await apply_job_tool(
            application_url="https://careers.example.com/captcha-verify",
            resume_file_path=sample_pdf_path,
            user_profile={"email": "test@example.com"},
            company="CaptchaCorp",
            job_title="Dev",
            mock_mode=True,
        )
        data = json.loads(res)
        assert data["status"] == "MANUAL_ACTION_REQUIRED"

    @pytest.mark.asyncio
    async def test_signup_url_returns_manual(self, sample_pdf_path):
        res = await apply_job_tool(
            application_url="https://careers.example.com/signup/new",
            resume_file_path=sample_pdf_path,
            user_profile={"email": "test@example.com"},
            company="SignupCorp",
            job_title="Dev",
            mock_mode=True,
        )
        data = json.loads(res)
        assert data["status"] == "MANUAL_ACTION_REQUIRED"

