"""Tests for Phase 4 & 5: Application Automation, Adapters, Verification, and Security Barriers."""

import json
import pytest

from mcp_server.tools.apply_job import apply_job_tool
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
