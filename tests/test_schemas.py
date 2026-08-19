"""Tests for Pydantic schemas."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    ApplicationResult,
    EmailSummary,
    JobListing,
    ManualActionItem,
    MatchedJob,
    ResumeChunk,
    ResumeMetadata,
    StartJobSearchRequest,
    UploadResumeResponse,
    UserProfile,
)


def test_user_profile_creation():
    profile = UserProfile(
        role="Java Developer",
        skills=["Java", "Spring Boot"],
        experience=3,
        locations=["Pune"],
        email="user@test.com",
        full_name="Test User",
        phone="123",
    )
    assert profile.role == "Java Developer"
    assert profile.email == "user@test.com"
    assert profile.experience == 3


def test_user_profile_defaults():
    profile = UserProfile(role="Dev", email="a@b.com")
    assert profile.skills == []
    assert profile.experience == 0
    assert profile.locations == []
    assert profile.full_name == ""
    assert profile.phone == ""


def test_user_profile_invalid_email():
    with pytest.raises(ValidationError):
        UserProfile(role="Dev", email="not-an-email")


def test_job_listing_schema():
    job = JobListing(
        job_id="job123",
        title="Software Engineer",
        company="Tech Corp",
        location="Remote",
        description="Write code.",
        application_url="https://example.com/apply",
        source="mcp",
        posted_at="2026-01-01",
    )
    assert job.company == "Tech Corp"
    assert job.title == "Software Engineer"


def test_job_listing_defaults():
    job = JobListing(title="Dev", company="Co", application_url="https://x.com")
    assert job.job_id == ""
    assert job.location == ""
    assert job.description == ""
    assert job.source == "web"


def test_matched_job_schema():
    match = MatchedJob(
        job_id="job123",
        title="Software Engineer",
        company="Tech Corp",
        application_url="https://example.com/apply",
        match_score=85,
        matching_skills=["Python"],
        missing_skills=["Java"],
        match_rationale="Good fit",
    )
    assert match.match_score == 85
    assert "Python" in match.matching_skills
    assert match.company == "Tech Corp"


def test_application_result():
    res = ApplicationResult(
        job_id="1",
        company="Acme",
        job_url="http://acme.com",
        status="SUCCESS",
        resume_used="res1.pdf",
        applied_at="2026-08-17T00:00:00",
    )
    assert res.status == "SUCCESS"
    assert res.company == "Acme"
    assert res.error is None


def test_application_result_with_error():
    res = ApplicationResult(
        job_id="2",
        company="XYZ",
        job_url="http://xyz.com",
        status="FAILED",
        resume_used="res1.pdf",
        error="Network timeout",
    )
    assert res.status == "FAILED"
    assert res.error == "Network timeout"


def test_resume_chunk():
    chunk = ResumeChunk(
        chunk_id="chunk1",
        content="This is resume content.",
        metadata={"page": 1},
    )
    assert chunk.chunk_id == "chunk1"
    assert chunk.content == "This is resume content."
    assert chunk.metadata["page"] == 1


def test_resume_metadata():
    meta = ResumeMetadata(
        extracted_skills=["Python", "C++"],
        experience_years=5,
        projects=["Project A"],
    )
    assert meta.experience_years == 5
    assert "Python" in meta.extracted_skills


def test_resume_metadata_defaults():
    meta = ResumeMetadata()
    assert meta.extracted_skills == []
    assert meta.experience_years is None
    assert meta.projects == []


def test_manual_action_item():
    action = ManualActionItem(
        company="Big Corp",
        job_url="http://bigcorp.com/apply",
        reason="Captcha required",
    )
    assert action.reason == "Captcha required"
    assert action.status == "PENDING_MANUAL_ACTION"


def test_email_summary():
    summary = EmailSummary(
        applied_successfully=5,
        manual_action_required=2,
        failed=1,
        pending_manual_jobs=[],
        applied_jobs=[],
        run_id="run-123",
    )
    assert summary.applied_successfully == 5
    assert summary.run_id == "run-123"


def test_email_summary_defaults():
    summary = EmailSummary()
    assert summary.applied_successfully == 0
    assert summary.failed == 0
    assert summary.pending_manual_jobs == []


def test_start_job_search_request():
    req = StartJobSearchRequest(
        user_id="u1",
        resume_id="r1",
        role="Java Dev",
        email="a@b.com",
    )
    assert req.user_id == "u1"
    assert req.skills == []
    assert req.match_threshold is None


def test_upload_resume_response():
    resp = UploadResumeResponse(
        user_id="u1",
        resume_id="r1",
        file_hash="abc123",
        message="OK",
        chunks_indexed=5,
    )
    assert resp.chunks_indexed == 5
