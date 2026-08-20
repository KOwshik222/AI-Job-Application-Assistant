"""Tests for MCP tools (search_jobs, apply_job, send_email)."""

import json
import pytest


@pytest.mark.asyncio
async def test_search_jobs_mock():
    from mcp_server.tools.search_jobs import search_jobs_tool

    result = await search_jobs_tool(
        role="Java Developer",
        skills=["Java", "Spring Boot"],
        locations=["Pune", "Mumbai"],
        experience_years=3,
        max_results=10,
        test_mode=True,
    )
    data = json.loads(result)
    assert "jobs" in data
    assert "total_found" in data
    assert len(data["jobs"]) > 0

    job = data["jobs"][0]
    assert "title" in job
    assert "company" in job
    assert "application_url" in job


@pytest.mark.asyncio
async def test_search_jobs_location_filter():
    from mcp_server.tools.search_jobs import search_jobs_tool

    result = await search_jobs_tool(
        role="Java Developer",
        locations=["Pune"],
        max_results=5,
        test_mode=True,
    )
    data = json.loads(result)
    for job in data["jobs"]:
        assert "pune" in job["location"].lower() or job["source"] == "tavily"


@pytest.mark.asyncio
async def test_apply_job_mock_success(sample_pdf_path):
    from mcp_server.tools.apply_job import apply_job_tool

    result = await apply_job_tool(
        application_url="https://careers.example.com/job/123",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "test@example.com", "full_name": "Test User"},
        company="Example Corp",
        job_title="Java Developer",
        mock_mode=True,
    )
    data = json.loads(result)
    assert data["status"] == "SUCCESS"
    assert "resume_used" in data


@pytest.mark.asyncio
async def test_apply_job_mock_login_required(sample_pdf_path):
    from mcp_server.tools.apply_job import apply_job_tool

    result = await apply_job_tool(
        application_url="https://careers.example.com/login/apply",
        resume_file_path=sample_pdf_path,
        user_profile={"email": "test@example.com"},
        mock_mode=True,
    )
    data = json.loads(result)
    assert data["status"] == "MANUAL_ACTION_REQUIRED"
    assert "Login" in data["reason"]


@pytest.mark.asyncio
async def test_apply_job_invalid_url(sample_pdf_path):
    from mcp_server.tools.apply_job import apply_job_tool

    result = await apply_job_tool(
        application_url="not-a-url",
        resume_file_path=sample_pdf_path,
        user_profile={},
        mock_mode=True,
    )
    data = json.loads(result)
    assert data["status"] == "FAILED"
    assert "Invalid" in data["reason"]


@pytest.mark.asyncio
async def test_apply_job_missing_resume():
    from mcp_server.tools.apply_job import apply_job_tool

    result = await apply_job_tool(
        application_url="https://example.com/apply",
        resume_file_path="/nonexistent/resume.pdf",
        user_profile={},
        mock_mode=True,
    )
    data = json.loads(result)
    assert data["status"] == "FAILED"
    assert "not found" in data["reason"]


@pytest.mark.asyncio
async def test_send_email_no_smtp():
    from mcp_server.tools.send_email import send_email_tool

    result = await send_email_tool(
        to_email="test@example.com",
        subject="Test Summary",
        summary={
            "applied_successfully": 3,
            "manual_action_required": 1,
            "failed": 0,
            "pending_manual_jobs": [],
            "applied_jobs": [],
            "run_id": "test-run-001",
        },
    )
    data = json.loads(result)
    # Without SMTP configured, should save locally
    assert data["status"] in ("NOT_CONFIGURED", "SENT")
    assert "to_email" in data
