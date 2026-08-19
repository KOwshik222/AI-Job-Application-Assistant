"""MCP tool: search_jobs — find job openings."""

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

MOCK_JOBS = [
    {
        "title": "Senior Java Developer",
        "company": "Infosys",
        "location": "Pune",
        "description": "Java, Spring Boot, Microservices, SQL. 3+ years experience required.",
        "application_url": "https://careers.infosys.com/job/java-developer-pune",
        "source": "mock",
        "posted_at": "2026-08-15",
    },
    {
        "title": "Java Backend Engineer",
        "company": "TCS",
        "location": "Mumbai",
        "description": "Build microservices with Java 17, Spring Boot, REST APIs, PostgreSQL.",
        "application_url": "https://careers.tcs.com/job/java-backend-mumbai",
        "source": "mock",
        "posted_at": "2026-08-14",
    },
    {
        "title": "Full Stack Java Developer",
        "company": "Wipro",
        "location": "Bangalore",
        "description": "Java, Spring Boot, React, AWS, Docker. Agile team.",
        "application_url": "https://careers.wipro.com/job/fullstack-java",
        "source": "mock",
        "posted_at": "2026-08-13",
    },
    {
        "title": "Java Microservices Developer",
        "company": "Accenture",
        "location": "Pune",
        "description": "Design and deploy Java microservices on cloud platforms.",
        "application_url": "https://careers.accenture.com/job/java-microservices",
        "source": "mock",
        "posted_at": "2026-08-12",
    },
    {
        "title": "Java Architect",
        "company": "TechMahindra",
        "location": "Mumbai",
        "description": "Java, Spring Boot, AWS, Kafka, Microservices. 5+ years experience.",
        "application_url": "https://careers.techmahindra.com/login/java-architect",
        "source": "mock",
        "posted_at": "2026-08-10",
    },
]

EXCLUDED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "wikipedia.org",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "medium.com",
    "quora.com",
    "reddit.com",
    "coursera.org",
    "udemy.com",
)

EXCLUDED_TITLE_KEYWORDS = (
    "questions",
    "interview",
    "trends",
    "opportunities & trends",
    "roadmap",
    "how to become",
    "bootcamp",
    "course",
    "syllabus",
    "tutorial",
    "salary",
    "guide",
)


def _clean_company_and_title(raw_title: str, default_role: str) -> tuple[str, str]:
    """Parse out realistic company name and job title from web search title."""
    title_str = raw_title.strip()

    # Common patterns:
    # "Software Engineer at Google - Mountain View, CA"
    # "Google hiring Software Engineer in Bangalore"
    # "Senior AI Developer - Microsoft - Hyderabad"
    # "Amazon - Machine Learning Engineer - Seattle"
    parts = [p.strip() for p in re.split(r"[-|–—:]", title_str) if p.strip()]

    company = "Tech Company"
    job_title = default_role

    # Pattern: "Company hiring Role"
    hiring_match = re.search(r"^(.*?)\s+(?:is\s+)?hiring\s+(.*?)(?:\s+in\s+.*)?$", title_str, re.IGNORECASE)
    if hiring_match:
        company = hiring_match.group(1).strip()
        job_title = hiring_match.group(2).strip()
        return company[:60], job_title[:80]

    # Pattern: "Role at Company"
    at_match = re.search(r"^(.*?)\s+at\s+(.*?)(?:\s+in\s+.*|\s*[-|–].*)?$", title_str, re.IGNORECASE)
    if at_match:
        job_title = at_match.group(1).strip()
        company = at_match.group(2).strip()
        return company[:60], job_title[:80]

    if len(parts) >= 2:
        # Check if first part is company or title
        if any(role_word.lower() in parts[0].lower() for role_word in default_role.split()):
            job_title = parts[0]
            company = parts[1]
        else:
            company = parts[0]
            job_title = parts[1]
    elif len(parts) == 1:
        job_title = parts[0]
        company = "Direct Hire"

    # Clean generic aggregator names
    if re.search(r"\d+\+?\s*jobs", company, re.IGNORECASE) or "careers" in company.lower() or "opportunities" in company.lower():
        # Try to extract company from URL if title was generic
        company = "Direct Employer"

    return company[:60], job_title[:80]


async def _search_tavily(role: str, locations: list[str], max_results: int) -> list[dict]:
    if not settings.tavily_api_key:
        return []

    try:
        from langchain_community.tools.tavily_search import TavilySearchResults

        loc_str = " OR ".join(locations) if locations else "India"
        
        # We query for specific direct job postings & applicant portals
        queries = [
            f'"{role}" hiring ({loc_str}) ("apply" OR "careers" OR "job opening")',
            f'"{role}" ({loc_str}) ("jobs.lever.co" OR "greenhouse.io" OR "myworkdayjobs.com" OR "linkedin.com/jobs/view" OR "smartrecruiters.com")',
        ]

        jobs: list[dict] = []
        seen_urls: set[str] = set()

        tool = TavilySearchResults(max_results=max(10, max_results // 2), tavily_api_key=settings.tavily_api_key)

        for query in queries:
            try:
                results = tool.invoke({"query": query})
            except Exception as e:
                logger.warning("Tavily query failed: %s", e)
                continue

            for r in results:
                url = r.get("url", "").strip()
                if not url or url in seen_urls:
                    continue

                if any(dom in url.lower() for dom in EXCLUDED_DOMAINS):
                    continue

                raw_title = r.get("title", "").strip()
                if any(k in raw_title.lower() for k in EXCLUDED_TITLE_KEYWORDS):
                    continue

                seen_urls.add(url)
                company, job_title = _clean_company_and_title(raw_title, role)

                jobs.append({
                    "title": job_title,
                    "company": company,
                    "location": locations[0] if locations else "Remote",
                    "description": r.get("content", ""),
                    "application_url": url,
                    "source": "tavily",
                    "posted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                })

                if len(jobs) >= max_results:
                    break

            if len(jobs) >= max_results:
                break

        return jobs
    except Exception as exc:
        logger.error("Error in Tavily job search: %s", exc)
        return []


async def search_jobs_tool(
    role: str,
    skills: list[str] | None = None,
    locations: list[str] | None = None,
    experience_years: int = 0,
    max_results: int = 30,
) -> str:
    locations = locations or []
    skills = skills or []

    jobs = await _search_tavily(role, locations, max_results)

    if not jobs:
        jobs = []
        for mock in MOCK_JOBS:
            loc_match = not locations or any(
                loc.lower() in mock["location"].lower() for loc in locations
            )
            if loc_match:
                jobs.append({**mock, "job_id": str(uuid.uuid4())})
        jobs = jobs[:max_results]

    return json.dumps({"jobs": jobs, "total_found": len(jobs)})
