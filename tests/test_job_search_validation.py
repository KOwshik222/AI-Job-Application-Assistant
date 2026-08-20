"""Tests for Phase 2 & Issue 1: Job Discovery, Actual Page Inspection, Extraction, and Validation."""

import json
import pytest

from mcp_server.tools.search_jobs import (
    canonicalize_url,
    is_candidate_url_structure,
    search_jobs_tool,
)


def test_canonicalize_url():
    url = "https://boards.greenhouse.io/stripe/jobs/12345?utm_source=linkedin&utm_medium=job_post&gh_src=abc#apply"
    canonical = canonicalize_url(url)
    assert canonical == "https://boards.greenhouse.io/stripe/jobs/12345"
    assert "utm_source" not in canonical
    assert "#apply" not in canonical


def test_candidate_url_structure_ats():
    # Valid individual ATS job URLs
    assert is_candidate_url_structure("https://boards.greenhouse.io/airbnb/jobs/456789") is True
    assert is_candidate_url_structure("https://jobs.lever.co/netflix/a1b2c3d4-e5f6") is True
    assert is_candidate_url_structure("https://nvidia.myworkdayjobs.com/NVIDIA/job/AI-Engineer") is True
    assert is_candidate_url_structure("https://jobs.smartrecruiters.com/Acme/123456") is True
    assert is_candidate_url_structure("https://www.linkedin.com/jobs/view/3829102938") is True


def test_candidate_url_structure_rejects_aggregators_and_search():
    # Reject search result and multi-job directory pages
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


@pytest.mark.asyncio
async def test_search_jobs_tool_mock_mode_only_when_explicit():
    # In test mode, returns mock jobs
    res_test = await search_jobs_tool(
        role="Java Developer",
        locations=["Pune"],
        max_results=5,
        test_mode=True,
    )
    data_test = json.loads(res_test)
    assert data_test["status"] == "TEST_MOCK_DATA"
    assert len(data_test["jobs"]) > 0

    # In production with test_mode=False and no key, never returns mock jobs
    res_prod = await search_jobs_tool(
        role="Java Developer",
        locations=["Pune"],
        max_results=5,
        test_mode=False,
    )
    data_prod = json.loads(res_prod)
    # When Tavily is configured it will search or return LIVE status
    assert data_prod["status"] in ("SUCCESS", "LIVE_JOB_SEARCH_UNAVAILABLE", "NO_MATCHING_JOBS_FOUND")
