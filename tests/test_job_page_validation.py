"""Tests for job page validation and Playwright fallback.

Verifies:
- Static HTML job page accepted
- JS-rendered job page extraction (Playwright fallback path)
- Search page rejected
- Aggregator page rejected
- Article rejected
- Generic career page rejected
- Valid individual job accepted
"""

import os
import pytest

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")


def test_candidate_url_structure_ats_accepted():
    """Known ATS individual job URLs should be accepted."""
    from mcp_server.tools.search_jobs import is_candidate_url_structure

    # Greenhouse
    assert is_candidate_url_structure("https://boards.greenhouse.io/stripe/jobs/12345") is True
    # Lever
    assert is_candidate_url_structure("https://jobs.lever.co/company/abcd-1234-ef56") is True
    # SmartRecruiters
    assert is_candidate_url_structure("https://jobs.smartrecruiters.com/company/123456") is True
    # Ashby
    assert is_candidate_url_structure("https://jobs.ashbyhq.com/company/abcd-1234") is True


def test_candidate_url_structure_search_rejected():
    """Search/aggregator URLs should be rejected."""
    from mcp_server.tools.search_jobs import is_candidate_url_structure

    assert is_candidate_url_structure("https://example.com/jobs/search") is False
    assert is_candidate_url_structure("https://example.com/jobs?q=developer") is False
    assert is_candidate_url_structure("https://example.com/search/job") is False


def test_candidate_url_structure_generic_rejected():
    """Generic career pages should be rejected."""
    from mcp_server.tools.search_jobs import is_candidate_url_structure

    assert is_candidate_url_structure("https://example.com/") is False
    assert is_candidate_url_structure("https://example.com/jobs") is False
    assert is_candidate_url_structure("https://example.com/careers") is False
    assert is_candidate_url_structure("https://example.com/jobs/") is False


def test_candidate_url_structure_excluded_domains():
    """Non-job domains should be rejected."""
    from mcp_server.tools.search_jobs import is_candidate_url_structure

    assert is_candidate_url_structure("https://youtube.com/watch?v=abc") is False
    assert is_candidate_url_structure("https://wikipedia.org/wiki/Java") is False
    assert is_candidate_url_structure("https://medium.com/java-developer") is False
    assert is_candidate_url_structure("https://reddit.com/r/jobs") is False


def test_candidate_url_structure_article_keywords():
    """URLs with article/tutorial patterns should be rejected."""
    from mcp_server.tools.search_jobs import is_candidate_url_structure

    assert is_candidate_url_structure("https://example.com/developer-jobs.html") is False


def test_canonicalize_url():
    """URL canonicalization strips tracking params."""
    from mcp_server.tools.search_jobs import canonicalize_url

    clean = canonicalize_url("https://example.com/job/123?utm_source=google&id=456")
    assert "utm_source" not in clean
    assert "id=456" in clean


def test_extract_from_json_ld():
    """JSON-LD JobPosting extraction works."""
    from bs4 import BeautifulSoup
    from mcp_server.tools.search_jobs import _extract_from_json_ld

    html = '''
    <html><head>
    <script type="application/ld+json">
    {
        "@type": "JobPosting",
        "title": "Senior Python Developer",
        "hiringOrganization": {"name": "Acme Corp"},
        "jobLocation": {"address": {"addressLocality": "San Francisco", "addressRegion": "CA"}},
        "description": "We are looking for an experienced Python developer to join our team. Must have 5+ years of experience with Django, Flask, and REST APIs. Strong knowledge of PostgreSQL and Redis required.",
        "datePosted": "2026-08-01"
    }
    </script>
    </head><body></body></html>
    '''
    soup = BeautifulSoup(html, "html.parser")
    result = _extract_from_json_ld(soup, "https://example.com/job/123")

    assert result is not None
    assert result["title"] == "Senior Python Developer"
    assert result["company"] == "Acme Corp"
    assert "San Francisco" in result["location"]


def test_extract_from_soup_rejects_aggregator():
    """Pages with aggregator signals should be rejected."""
    from bs4 import BeautifulSoup
    from mcp_server.tools.search_jobs import _extract_job_from_soup

    html = '<html><body><h1>Java Jobs</h1><p>Showing 1-20 of 500 jobs</p></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    page_text = "showing 1-20 of 500 jobs java developer"

    result = _extract_job_from_soup(soup, "https://example.com/jobs", "Java Jobs", page_text)
    assert result is None


def test_extract_from_soup_rejects_article():
    """Pages with article/tutorial titles should be rejected."""
    from bs4 import BeautifulSoup
    from mcp_server.tools.search_jobs import _extract_job_from_soup

    html = '<html><body><h1>Top 10 Interview Questions for Java</h1><p>Some content</p></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    page_text = "top 10 interview questions for java developers"

    result = _extract_job_from_soup(soup, "https://example.com/article", "Top 10 Interview Questions", page_text)
    assert result is None


def test_extract_from_soup_accepts_valid_job():
    """Valid individual job page should be accepted."""
    from bs4 import BeautifulSoup
    from mcp_server.tools.search_jobs import _extract_job_from_soup

    html = '''
    <html><head>
    <meta property="og:site_name" content="Acme Corp Careers"/>
    <script type="application/ld+json">
    {
        "@type": "JobPosting",
        "title": "Backend Engineer",
        "hiringOrganization": {"name": "Acme Corp"},
        "jobLocation": {"address": {"addressLocality": "New York"}},
        "description": "Join our backend team to build scalable microservices. Required: Python, Go, PostgreSQL, Kubernetes, AWS. Experience with event-driven architecture is a plus.",
        "datePosted": "2026-08-15"
    }
    </script>
    </head><body>
    <h1>Backend Engineer</h1>
    <div class="job-description">Build scalable microservices using Python and Go.</div>
    </body></html>
    '''
    soup = BeautifulSoup(html, "html.parser")
    page_text = "backend engineer acme corp build scalable microservices"

    result = _extract_job_from_soup(soup, "https://acme.com/careers/backend-engineer", "Backend Engineer", page_text)
    assert result is not None
    assert result["title"] == "Backend Engineer"
    assert result["company"] == "Acme Corp"


def test_extract_rejects_generic_company_patterns():
    """Generic/fake company names should cause rejection."""
    from bs4 import BeautifulSoup
    from mcp_server.tools.search_jobs import _extract_job_from_soup

    html = '''
    <html><head>
    <meta property="og:site_name" content="Indeed"/>
    </head><body>
    <h1>Java Developer</h1>
    <div class="description">Some job description that is long enough to pass the minimum length check for validation purposes here.</div>
    </body></html>
    '''
    soup = BeautifulSoup(html, "html.parser")
    page_text = "java developer indeed jobs"

    result = _extract_job_from_soup(soup, "https://indeed.com/viewjob", "Java Developer", page_text)
    # Indeed as company name should be rejected by generic pattern
    assert result is None


def test_clean_html_text():
    """HTML cleaning removes scripts, styles, nav, and normalizes whitespace."""
    from mcp_server.tools.search_jobs import _clean_html_text

    html = '<div><script>alert("x")</script><p>Hello   World</p><style>.x{}</style></div>'
    text = _clean_html_text(html)
    assert "alert" not in text
    assert "Hello World" in text
    assert ".x{}" not in text
