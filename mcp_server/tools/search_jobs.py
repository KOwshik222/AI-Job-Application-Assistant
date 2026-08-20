"""MCP tool: search_jobs — find and validate individual job openings."""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

MOCK_JOBS = [
    {
        "title": "Senior Java Developer",
        "company": "Infosys",
        "location": "Pune",
        "description": "Develop enterprise microservices using Java 17, Spring Boot, Microservices, PostgreSQL, and AWS. 3+ years experience required.",
        "application_url": "https://careers.infosys.com/job/java-developer-pune",
        "source": "mock",
        "posted_at": "2026-08-15",
    },
    {
        "title": "Java Backend Engineer",
        "company": "Tata Consultancy Services",
        "location": "Mumbai",
        "description": "Build high-throughput microservices with Java 17, Spring Boot, REST APIs, Kafka, and PostgreSQL. Agile cross-functional team.",
        "application_url": "https://careers.tcs.com/job/java-backend-mumbai",
        "source": "mock",
        "posted_at": "2026-08-14",
    },
    {
        "title": "Full Stack Java Developer",
        "company": "Wipro",
        "location": "Bangalore",
        "description": "Java, Spring Boot, React, AWS, Docker, Kubernetes. Designing scalable distributed cloud native web applications.",
        "application_url": "https://careers.wipro.com/job/fullstack-java",
        "source": "mock",
        "posted_at": "2026-08-13",
    },
    {
        "title": "Java Microservices Developer",
        "company": "Accenture",
        "location": "Pune",
        "description": "Design and deploy cloud-native Java microservices on AWS and GCP with Kubernetes, Docker, and CI/CD pipelines.",
        "application_url": "https://careers.accenture.com/job/java-microservices",
        "source": "mock",
        "posted_at": "2026-08-12",
    },
    {
        "title": "Java Cloud Architect",
        "company": "Tech Mahindra",
        "location": "Mumbai",
        "description": "Lead enterprise architecture for Java, Spring Boot, AWS, Kafka, Microservices, and Event-Driven systems. 5+ years experience.",
        "application_url": "https://careers.techmahindra.com/job/java-architect",
        "source": "mock",
        "posted_at": "2026-08-10",
    },
]

# Domains to immediately reject (non-job content)
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
    "geeksforgeeks.org",
    "tutorialspoint.com",
    "javatpoint.com",
    "w3schools.com",
    "leetcode.com",
    "hackerrank.com",
)

# Reject titles containing non-job keywords
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
    "top 10",
    "top 20",
    "top careers",
    "best careers",
    "what is",
    "vs",
    "cheat sheet",
)

# Aggregator search URL patterns that represent lists of jobs rather than single jobs
AGGREGATOR_SEARCH_PATTERNS = (
    r"/jobs/search",
    r"/jobs\?q=",
    r"/q-",
    r"/role/l/",
    r"-jobs\.html",
    r"-jobs$",
    r"/k/",
    r"/fresher-jobs/",
    r"/search/job",
    r"/search\?",
)

# Generic company name patterns that indicate fake or aggregator extractions
GENERIC_COMPANY_PATTERNS = (
    r"^\d+\+?\s*",
    r"jobs?",
    r"careers?",
    r"hiring",
    r"remote",
    r"fresher",
    r"vacancies",
    r"opportunities",
    r"tech company",
    r"direct hire",
    r"direct employer",
    r"unknown",
    r"google search",
    r"indeed",
    r"glassdoor",
    r"naukri",
    r"linkedin",
    r"hirist",
    r"monster",
)


def canonicalize_url(raw_url: str) -> str:
    """Strip query tracking parameters and fragment to canonicalize URL."""
    try:
        parsed = urlparse(raw_url.strip())
        if not parsed.scheme or not parsed.netloc:
            return ""

        # Filter out tracking query params
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "ref", "gh_src", "source", "refId", "trackingId", "position", "pageNum",
        }
        query_dict = parse_qs(parsed.query)
        cleaned_query = {k: v for k, v in query_dict.items() if k not in tracking_params}
        encoded_query = urlencode(cleaned_query, doseq=True)

        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            encoded_query,
            "",  # strip fragment
        ))
    except Exception:
        return raw_url.strip()


def is_individual_job_url(url: str) -> bool:
    """Check whether a URL represents an individual job posting vs aggregator/search page."""
    parsed = urlparse(url.lower())
    netloc = parsed.netloc
    path = parsed.path
    query = parsed.query

    # Reject non-job domains
    if any(dom in netloc for dom in EXCLUDED_DOMAINS):
        return False

    # Check for known ATS individual job patterns
    ats_individual_patterns = [
        r"boards\.greenhouse\.io/[^/]+/jobs/\d+",
        r"jobs\.lever\.co/[^/]+/[a-f0-9-]+",
        r"[\w-]+\.myworkdayjobs\.com/[^/]+/[\w-]+/job/",
        r"jobs\.smartrecruiters\.com/[^/]+/\d+",
        r"jobs\.ashbyhq\.com/[^/]+/[a-f0-9-]+",
        r"apply\.workable\.com/[^/]+/j/[A-Z0-9]+",
        r"careers\.[^/]+/job/",
        r"linkedin\.com/jobs/view/\d+",
        r"indeed\.com/viewjob",
        r"indeed\.com/rc/clk",
        r"/careers/[^/]+/job/[^/]+",
        r"/jobs/[^/]+/[a-f0-9-]+",
    ]
    for pattern in ats_individual_patterns:
        if re.search(pattern, f"{netloc}{path}"):
            return True

    # Reject search result/category pages
    for pattern in AGGREGATOR_SEARCH_PATTERNS:
        if re.search(pattern, path) or re.search(pattern, f"?{query}"):
            return False

    # Reject bare root domain or top-level /jobs or /careers
    if path in ("", "/", "/jobs", "/careers", "/jobs/", "/careers/"):
        return False

    return True


def extract_real_company_and_title(raw_title: str, default_role: str, url: str) -> tuple[str | None, str | None]:
    """Extract and validate real company name and job title from page title / metadata.
    
    Returns (company, job_title) if valid, or (None, None) if page is invalid/generic.
    """
    title_str = raw_title.strip()
    if not title_str:
        return None, None

    # Check for excluded keywords in title
    if any(k in title_str.lower() for k in EXCLUDED_TITLE_KEYWORDS):
        return None, None

    # Common separator split: "Job Title - Company - Location" or "Company - Job Title"
    parts = [p.strip() for p in re.split(r"[-|–—:]", title_str) if p.strip()]

    company = None
    job_title = None

    # Pattern 1: "Company is hiring Job Title" or "Company hiring Job Title"
    hiring_match = re.search(r"^(.*?)\s+(?:is\s+)?hiring\s+(.*?)(?:\s+in\s+.*|\s*[-|–].*)?$", title_str, re.IGNORECASE)
    if hiring_match:
        company = hiring_match.group(1).strip()
        job_title = hiring_match.group(2).strip()

    # Pattern 2: "Job Title at Company"
    if not company:
        at_match = re.search(r"^(.*?)\s+at\s+(.*?)(?:\s+in\s+.*|\s*[-|–].*)?$", title_str, re.IGNORECASE)
        if at_match:
            job_title = at_match.group(1).strip()
            company = at_match.group(2).strip()

    # Pattern 3: Separator parts
    if not company and len(parts) >= 2:
        # Check if first part matches role keywords
        first_part_matches_role = any(w.lower() in parts[0].lower() for w in default_role.split() if len(w) > 2)
        if first_part_matches_role:
            job_title = parts[0]
            company = parts[1]
        else:
            company = parts[0]
            job_title = parts[1]
    elif not company and len(parts) == 1:
        job_title = parts[0]
        # Attempt to infer company from ATS URL domain (e.g. boards.greenhouse.io/stripe/jobs -> Stripe)
        url_match = re.search(r"(?:greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|workable\.com)/([^/]+)", url)
        if url_match:
            company = url_match.group(1).replace("-", " ").title()

    if not company or not job_title:
        return None, None

    # Clean company and title strings
    company = re.sub(r"\s+", " ", company).strip()
    job_title = re.sub(r"\s+", " ", job_title).strip()

    # Reject if company matches generic aggregator phrases
    for pattern in GENERIC_COMPANY_PATTERNS:
        if re.search(pattern, company, re.IGNORECASE):
            return None, None

    # Reject if title matches aggregator phrases
    if re.search(r"\d+\+?\s*jobs?", job_title, re.IGNORECASE):
        return None, None

    # Length sanity check
    if len(company) < 2 or len(company) > 80:
        return None, None
    if len(job_title) < 3 or len(job_title) > 120:
        return None, None

    return company, job_title


async def _search_tavily(
    role: str,
    skills: list[str],
    locations: list[str],
    experience_years: int,
    max_results: int,
) -> list[dict]:
    """Execute targeted Tavily search for individual job postings and extract structured data."""
    if not settings.tavily_api_key:
        return []

    try:
        from langchain_community.tools.tavily_search import TavilySearchResults

        loc_str = " OR ".join(locations) if locations else "India"
        skills_str = " ".join(skills[:3]) if skills else ""

        # Targeted queries specifically finding individual job postings across ATS & portals
        queries = [
            f'"{role}" ({loc_str}) ("boards.greenhouse.io" OR "jobs.lever.co" OR "myworkdayjobs.com" OR "jobs.smartrecruiters.com" OR "jobs.ashbyhq.com")',
            f'"{role}" {skills_str} ({loc_str}) ("apply" OR "job description") ("requirements" OR "responsibilities")',
            f'"{role}" ({loc_str}) ("careers" OR "job opening") site:linkedin.com/jobs/view OR site:indeed.com/viewjob',
        ]

        jobs: list[dict] = []
        seen_canonical_urls: set[str] = set()
        seen_job_signatures: set[tuple[str, str, str]] = set()

        tool = TavilySearchResults(
            max_results=max(8, max_results // len(queries) + 3),
            tavily_api_key=settings.tavily_api_key,
        )

        for query in queries:
            if len(jobs) >= max_results:
                break

            try:
                results = tool.invoke({"query": query})
            except Exception as e:
                logger.warning("Tavily query failed for '%s': %s", query, e)
                continue

            if not isinstance(results, list):
                continue

            for r in results:
                raw_url = r.get("url", "").strip()
                raw_title = r.get("title", "").strip()
                content = r.get("content", "").strip()

                if not raw_url or not raw_title:
                    continue

                canonical_url = canonicalize_url(raw_url)
                if not canonical_url or canonical_url in seen_canonical_urls:
                    continue

                # Validate individual job posting URL
                if not is_individual_job_url(canonical_url):
                    continue

                # Extract and validate real company and title
                company, job_title = extract_real_company_and_title(raw_title, role, canonical_url)
                if not company or not job_title:
                    continue

                # Description must be meaningful (> 30 characters)
                if len(content) < 30:
                    continue

                # Deduplicate by (company, normalized_title, location)
                norm_company = re.sub(r"[^\w]", "", company.lower())
                norm_title = re.sub(r"[^\w]", "", job_title.lower())
                norm_loc = locations[0].lower() if locations else ""
                sig = (norm_company, norm_title, norm_loc)

                if sig in seen_job_signatures:
                    continue

                seen_canonical_urls.add(canonical_url)
                seen_job_signatures.add(sig)

                jobs.append({
                    "job_id": str(uuid.uuid4()),
                    "title": job_title,
                    "company": company,
                    "location": locations[0] if locations else "Remote",
                    "description": content,
                    "application_url": canonical_url,
                    "source": "tavily",
                    "posted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                })

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
    """MCP tool implementation to search, validate, and return real individual job listings."""
    locations = locations or []
    skills = skills or []

    jobs = await _search_tavily(
        role=role,
        skills=skills,
        locations=locations,
        experience_years=experience_years,
        max_results=max_results,
    )

    # Fallback to mock jobs only when live search is unconfigured or returned no valid individual jobs in demo
    if not jobs and not settings.tavily_api_key:
        logger.info("Tavily API key not configured — returning mock sample jobs for development/demo.")
        jobs = []
        for mock in MOCK_JOBS:
            loc_match = not locations or any(
                loc.lower() in mock["location"].lower() for loc in locations
            )
            if loc_match:
                jobs.append({**mock, "job_id": str(uuid.uuid4())})
        jobs = jobs[:max_results]

    return json.dumps({
        "jobs": jobs,
        "total_found": len(jobs),
        "source": "tavily" if settings.tavily_api_key else "mock",
    })
