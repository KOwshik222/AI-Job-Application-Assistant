"""Tests for Job Discovery, Actual Page Inspection, Extraction, and Validation."""

import asyncio
import json
import os
import unittest.mock as mock
import pytest

import mcp_server.tools.search_jobs as sj_mod
from mcp_server.tools.search_jobs import (
    canonicalize_url,
    fetch_and_inspect_job_page,
    is_candidate_url_structure,
    search_jobs_tool,
    _search_tavily,
    _playwright_render_page,
    EXCLUDED_TITLE_KEYWORDS,
)

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("DEMO_MODE", "false")


def test_canonicalize_url():
    url = "https://boards.greenhouse.io/stripe/jobs/12345?utm_source=linkedin&utm_medium=job_post&gh_src=abc#apply"
    canonical = canonicalize_url(url)
    assert canonical == "https://boards.greenhouse.io/stripe/jobs/12345"
    assert "utm_source" not in canonical
    assert "#apply" not in canonical


def test_candidate_url_structure_ats():
    assert is_candidate_url_structure("https://boards.greenhouse.io/airbnb/jobs/456789") is True
    assert is_candidate_url_structure("https://jobs.lever.co/netflix/a1b2c3d4-e5f6") is True
    assert is_candidate_url_structure("https://nvidia.myworkdayjobs.com/NVIDIA/job/AI-Engineer") is True
    assert is_candidate_url_structure("https://jobs.smartrecruiters.com/Acme/123456") is True
    assert is_candidate_url_structure("https://jobs.ashbyhq.com/Wisdom-AI/0a9c84e1-2b0e-4361-b552-87ff81db09bf") is True
    assert is_candidate_url_structure("https://apply.workable.com/techcorp/j/12345ABCDE") is True
    assert is_candidate_url_structure("https://www.linkedin.com/jobs/view/3829102938") is True


def test_ashby_company_listing_rejected():
    """Ashby company career/listing pages must be rejected."""
    assert is_candidate_url_structure("https://jobs.ashbyhq.com/Wisdom-AI") is False
    assert is_candidate_url_structure("https://jobs.ashbyhq.com/Wisdom-AI/") is False
    assert is_candidate_url_structure("https://jobs.ashbyhq.com/AcmeCorp") is False


def test_ashby_individual_job_accepted():
    """Ashby individual job URLs must be accepted."""
    assert is_candidate_url_structure("https://jobs.ashbyhq.com/Wisdom-AI/0a9c84e1-2b0e-4361-b552-87ff81db09bf") is True
    assert is_candidate_url_structure("https://jobs.ashbyhq.com/Acme/junior-ai-developer-418f7d98") is True


def test_lever_company_listing_rejected():
    """Lever company career/listing pages must be rejected."""
    assert is_candidate_url_structure("https://jobs.lever.co/netflix") is False
    assert is_candidate_url_structure("https://jobs.lever.co/netflix/") is False
    assert is_candidate_url_structure("https://jobs.lever.co/spotify") is False


def test_lever_individual_job_accepted():
    """Lever individual job URLs must be accepted."""
    assert is_candidate_url_structure("https://jobs.lever.co/netflix/4a796e95-7182-4217-bfef-c5b9f71c4c1a") is True
    assert is_candidate_url_structure("https://jobs.lever.co/spotify/e2c65a78-9012-4321-9876-123456789abc") is True


def test_workday_company_listing_rejected():
    """Workday company career/listing pages (without /job/) must be rejected."""
    assert is_candidate_url_structure("https://tbc.wd12.myworkdayjobs.com/en-US/LyricCareers") is False
    assert is_candidate_url_structure("https://tbc.wd12.myworkdayjobs.com/LyricCareers/") is False
    assert is_candidate_url_structure("https://db.wd3.myworkdayjobs.com/en-US/DBWebsite") is False


def test_workday_individual_job_accepted():
    """Workday individual job URLs (with /job/) must be accepted."""
    assert is_candidate_url_structure("https://tbc.wd12.myworkdayjobs.com/en-US/LyricCareers/job/Software-Engineer-I--AI_JR884") is True
    assert is_candidate_url_structure("https://db.wd3.myworkdayjobs.com/en-US/DBWebsite/job/AI-Specialist_R0441888") is True


def test_smartrecruiters_company_listing_rejected():
    """SmartRecruiters company career/listing pages must be rejected."""
    assert is_candidate_url_structure("https://jobs.smartrecruiters.com/IFS1") is False
    assert is_candidate_url_structure("https://jobs.smartrecruiters.com/IFS1/") is False
    assert is_candidate_url_structure("https://jobs.smartrecruiters.com/BoschGroup") is False


def test_smartrecruiters_individual_job_accepted():
    """SmartRecruiters individual job URLs must be accepted."""
    assert is_candidate_url_structure("https://jobs.smartrecruiters.com/IFS1/744000144170159-ai-machine-learning-engineer-python-loops") is True
    assert is_candidate_url_structure("https://jobs.smartrecruiters.com/BoschGroup/12345678-software-engineer") is True


def test_greenhouse_company_listing_rejected_and_individual_accepted():
    """Greenhouse company listing rejected and individual job accepted."""
    assert is_candidate_url_structure("https://boards.greenhouse.io/airbnb") is False
    assert is_candidate_url_structure("https://boards.greenhouse.io/airbnb/jobs") is False
    assert is_candidate_url_structure("https://boards.greenhouse.io/airbnb/jobs/456789") is True


def test_candidate_url_structure_rejects_aggregators_and_search():
    assert is_candidate_url_structure("https://www.linkedin.com/jobs/search/?keywords=java") is False
    assert is_candidate_url_structure("https://www.indeed.com/q-ai-developer-jobs.html") is False
    assert is_candidate_url_structure("https://www.naukri.com/java-developer-jobs") is False
    assert is_candidate_url_structure("https://www.hirist.tech/k/java-jobs") is False
    assert is_candidate_url_structure("https://wellfound.com/role/l/java-developer/india") is False
    assert is_candidate_url_structure("https://careers.google.com/jobs") is False


def test_candidate_url_structure_rejects_media_and_articles():
    assert is_candidate_url_structure("https://www.youtube.com/watch?v=123456") is False
    assert is_candidate_url_structure("https://medium.com/@user/top-ai-careers-2026") is False
    assert is_candidate_url_structure("https://en.wikipedia.org/wiki/Artificial_intelligence") is False


def test_reject_listing_and_article_titles():
    invalid_titles = [
        "1000+ AI Jobs in Hyderabad",
        "Top AI Careers 2026",
        "Best Java Developer Jobs in Pune",
        "2534 Java Developer Job Vacancies In Pune",
        "Java Interview Questions and Answers",
        "How to Become a Cloud Architect",
        "Page Not Found 404",
    ]
    for title in invalid_titles:
        assert any(k in title.lower() for k in EXCLUDED_TITLE_KEYWORDS), f"Failed to reject: {title}"


def test_reject_company_listing_titles():
    """Company listing page titles like 'Wisdom AI Jobs' or 'Google Careers' must be rejected."""
    from mcp_server.tools.search_jobs import is_role_compatible
    assert is_role_compatible("Wisdom AI Jobs", "AI Developer") is False
    assert is_role_compatible("Google Careers", "AI Developer") is False
    assert is_role_compatible("Open Positions", "AI Developer") is False
    assert is_role_compatible("Careers at Acme", "AI Developer") is False
    assert is_role_compatible("Acme Job Openings", "AI Developer") is False

    # Valid job titles must be accepted
    assert is_role_compatible("Junior AI Developer", "AI Developer") is True
    assert is_role_compatible("AI/Machine Learning Engineer - Python", "AI Developer") is True
    assert is_role_compatible("Software Engineer I, AI", "AI Developer") is True
    assert is_role_compatible("AI Specialist", "AI Developer") is True



@pytest.mark.asyncio
async def test_search_jobs_tool_mock_mode_only_when_explicit():
    res_test = await search_jobs_tool(
        role="Java Developer",
        locations=["Pune"],
        max_results=5,
        test_mode=True,
    )
    data_test = json.loads(res_test)
    assert data_test["status"] == "TEST_MOCK_DATA"
    assert len(data_test["jobs"]) > 0


@pytest.mark.asyncio
async def test_no_mock_job_fallback_in_production(monkeypatch):
    monkeypatch.setattr(sj_mod.settings, "demo_mode", False)
    monkeypatch.setattr(sj_mod.settings, "test_mode", False)
    monkeypatch.setattr(sj_mod.settings, "tavily_api_key", "")

    res = await search_jobs_tool(role="Java Developer", test_mode=False)
    data = json.loads(res)
    assert data["status"] == "LIVE_JOB_SEARCH_UNAVAILABLE"
    assert len(data["jobs"]) == 0


@pytest.mark.asyncio
async def test_tavily_timeout_handled_gracefully(monkeypatch):
    monkeypatch.setattr(sj_mod.settings, "tavily_api_key", "mock-tavily-key")
    with mock.patch("langchain_community.tools.tavily_search.TavilySearchResults.invoke") as mock_inv:
        mock_inv.side_effect = TimeoutError("Tavily request timed out")
        jobs = await _search_tavily(
            role="Java Developer",
            skills=["Java"],
            locations=["Pune"],
            experience_years=3,
            max_results=5,
        )
        assert isinstance(jobs, list)
        assert len(jobs) == 0


@pytest.mark.asyncio
async def test_individual_job_url_timeout():
    """Individual hanging URL times out and does not raise exception."""
    with mock.patch("httpx.AsyncClient.get", side_effect=TimeoutError("Connection timed out")):
        with mock.patch("mcp_server.tools.search_jobs._playwright_render_page", return_value=None):
            res = await fetch_and_inspect_job_page(
                url="https://jobs.lever.co/company/job-1",
                raw_title="Java Developer",
                default_role="Java Developer",
            )
            assert res is None


@pytest.mark.asyncio
async def test_playwright_timeout():
    """Playwright timeout is caught and returns None safely."""
    with mock.patch("playwright.async_api.async_playwright") as mock_pw:
        mock_pw.side_effect = TimeoutError("Playwright navigation timed out")
        res = await _playwright_render_page("https://example.com/job-js")
        assert res is None


@pytest.mark.asyncio
async def test_partial_search_results(monkeypatch):
    """If 1 URL fails and 1 URL succeeds, the successful job is returned."""
    monkeypatch.setattr(sj_mod.settings, "tavily_api_key", "mock-tavily-key")

    mock_valid_job = {
        "job_id": "job-123",
        "title": "Backend Java Engineer",
        "company": "Target Corp",
        "location": "Pune",
        "description": "Develop high-performance backends with Java, Spring Boot, and PostgreSQL.",
        "application_url": "https://boards.greenhouse.io/target/jobs/123",
        "source": "tavily_verified",
        "posted_at": "2026-08-20",
    }

    async def fake_inspect(url, raw_title=None, role=None, *args, **kwargs):
        if "failing" in url:
            return None
        return mock_valid_job

    with mock.patch("mcp_server.tools.search_jobs.fetch_and_inspect_job_page", side_effect=fake_inspect):
        with mock.patch("langchain_community.tools.tavily_search.TavilySearchResults.invoke") as mock_inv:
            mock_inv.return_value = [
                {"url": "https://boards.greenhouse.io/target/jobs/123", "title": "Backend Java Engineer"},
                {"url": "https://boards.greenhouse.io/failing/jobs/456", "title": "Failing Job"},
            ]
            jobs = await _search_tavily(
                role="Java Developer",
                skills=["Java"],
                locations=["Pune"],
                experience_years=3,
                max_results=5,
            )
            assert len(jobs) == 1
            assert jobs[0]["company"] == "Target Corp"
            assert jobs[0]["title"] == "Backend Java Engineer"


@pytest.mark.asyncio
async def test_required_job_fields():
    """All returned jobs must have title, company, location, description, application_url."""
    res_str = await search_jobs_tool(role="Java Developer", test_mode=True, max_results=5)
    data = json.loads(res_str)
    assert len(data["jobs"]) > 0
    for job in data["jobs"]:
        assert "title" in job and job["title"]
        assert "company" in job and job["company"]
        assert "location" in job and job["location"]
        assert "description" in job and job["description"]
        assert "application_url" in job and job["application_url"]
