"""Tests for Phase 2: Job Discovery, Individual Job Validation, Extraction, and Deduplication."""

import json
import pytest

from mcp_server.tools.search_jobs import (
    canonicalize_url,
    extract_real_company_and_title,
    is_individual_job_url,
    search_jobs_tool,
)


def test_canonicalize_url():
    url = "https://boards.greenhouse.io/stripe/jobs/12345?utm_source=linkedin&utm_medium=job_post&gh_src=abc#apply"
    canonical = canonicalize_url(url)
    assert canonical == "https://boards.greenhouse.io/stripe/jobs/12345"
    assert "utm_source" not in canonical
    assert "#apply" not in canonical


def test_is_individual_job_url_ats():
    # Valid individual ATS job URLs
    assert is_individual_job_url("https://boards.greenhouse.io/airbnb/jobs/456789") is True
    assert is_individual_job_url("https://jobs.lever.co/netflix/a1b2c3d4-e5f6") is True
    assert is_individual_job_url("https://nvidia.myworkdayjobs.com/NVIDIA/job/AI-Engineer") is True
    assert is_individual_job_url("https://jobs.smartrecruiters.com/Acme/123456") is True
    assert is_individual_job_url("https://www.linkedin.com/jobs/view/3829102938") is True


def test_is_individual_job_url_rejects_aggregators_and_search():
    # Reject search result and multi-job directory pages
    assert is_individual_job_url("https://www.linkedin.com/jobs/search/?keywords=java") is False
    assert is_individual_job_url("https://www.indeed.com/q-ai-developer-jobs.html") is False
    assert is_individual_job_url("https://www.naukri.com/java-developer-jobs") is False
    assert is_individual_job_url("https://www.hirist.tech/k/java-jobs") is False
    assert is_individual_job_url("https://wellfound.com/role/l/java-developer/india") is False
    assert is_individual_job_url("https://careers.google.com/jobs") is False


def test_is_individual_job_url_rejects_media_and_articles():
    assert is_individual_job_url("https://www.youtube.com/watch?v=123456") is False
    assert is_individual_job_url("https://medium.com/@user/top-ai-careers-2026") is False
    assert is_individual_job_url("https://en.wikipedia.org/wiki/Artificial_intelligence") is False


def test_extract_real_company_and_title():
    # Format: Role at Company
    comp, title = extract_real_company_and_title(
        "Senior AI Engineer at Microsoft - Hyderabad", "AI Engineer", "https://careers.microsoft.com/job/1"
    )
    assert comp == "Microsoft"
    assert "AI Engineer" in title

    # Format: Company hiring Role
    comp, title = extract_real_company_and_title(
        "Google is hiring Senior Software Engineer in Bengaluru", "Software Engineer", "https://careers.google.com/job/2"
    )
    assert comp == "Google"
    assert "Software Engineer" in title

    # Greenhouse ATS URL
    comp, title = extract_real_company_and_title(
        "Backend Developer", "Backend Developer", "https://boards.greenhouse.io/stripe/jobs/123"
    )
    assert comp == "Stripe"
    assert title == "Backend Developer"


def test_rejects_generic_fake_company_and_title():
    # Reject aggregator titles
    comp, title = extract_real_company_and_title(
        "1,000+ AI Developer jobs in Hyderabad", "AI Developer", "https://example.com"
    )
    assert comp is None and title is None

    # Reject article/trend titles
    comp, title = extract_real_company_and_title(
        "Top AI careers in 2026: Opportunities & Trends", "AI Developer", "https://example.com"
    )
    assert comp is None and title is None

    # Reject interview questions
    comp, title = extract_real_company_and_title(
        "Top 50 Java Interview Questions and Answers", "Java Developer", "https://example.com"
    )
    assert comp is None and title is None


@pytest.mark.asyncio
async def test_search_jobs_tool_returns_structured_jobs():
    res = await search_jobs_tool(
        role="Java Developer",
        skills=["Java", "Spring Boot"],
        locations=["Pune"],
        max_results=5,
    )
    data = json.loads(res)
    assert "jobs" in data
    assert len(data["jobs"]) > 0
    for job in data["jobs"]:
        assert job["company"] not in ("Tech Company", "Direct Employer", "Direct Hire")
        assert len(job["company"]) >= 2
        assert len(job["title"]) >= 3
        assert len(job["description"]) > 20
        assert is_individual_job_url(job["application_url"]) is True
