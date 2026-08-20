"""MCP tool: search_jobs — fetches, inspects, validates, and extracts individual job postings."""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

MOCK_JOBS = [
    {
        "job_id": "mock-job-001",
        "title": "Senior Java Developer",
        "company": "Infosys",
        "location": "Pune",
        "description": "Develop enterprise microservices using Java 17, Spring Boot, Microservices, PostgreSQL, and AWS. 3+ years experience required.",
        "application_url": "https://careers.infosys.com/job/java-developer-pune",
        "source": "mock",
        "posted_at": "2026-08-15",
    },
    {
        "job_id": "mock-job-002",
        "title": "Java Backend Engineer",
        "company": "Tata Consultancy Services",
        "location": "Mumbai",
        "description": "Build high-throughput microservices with Java 17, Spring Boot, REST APIs, Kafka, and PostgreSQL. Agile cross-functional team.",
        "application_url": "https://careers.tcs.com/job/java-backend-mumbai",
        "source": "mock",
        "posted_at": "2026-08-14",
    },
    {
        "job_id": "mock-job-003",
        "title": "Full Stack Java Developer",
        "company": "Wipro",
        "location": "Bangalore",
        "description": "Java, Spring Boot, React, AWS, Docker, Kubernetes. Designing scalable distributed cloud native web applications.",
        "application_url": "https://careers.wipro.com/job/fullstack-java",
        "source": "mock",
        "posted_at": "2026-08-13",
    },
    {
        "job_id": "mock-job-004",
        "title": "Java Microservices Developer",
        "company": "Accenture",
        "location": "Pune",
        "description": "Design and deploy cloud-native Java microservices on AWS and GCP with Kubernetes, Docker, and CI/CD pipelines.",
        "application_url": "https://careers.accenture.com/job/java-microservices",
        "source": "mock",
        "posted_at": "2026-08-12",
    },
    {
        "job_id": "mock-job-005",
        "title": "Java Cloud Architect",
        "company": "Tech Mahindra",
        "location": "Mumbai",
        "description": "Lead enterprise architecture for Java, Spring Boot, AWS, Kafka, Microservices, and Event-Driven systems. 5+ years experience.",
        "application_url": "https://careers.techmahindra.com/job/java-architect",
        "source": "mock",
        "posted_at": "2026-08-10",
    },
]

# Non-job domains to reject immediately
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

# Reject titles containing non-job / article keywords
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
    "cheat sheet",
)

# Patterns that indicate search / category aggregator pages (not single jobs)
AGGREGATOR_URL_PATTERNS = (
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

# Patterns indicating fake or aggregator company names
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
    r"foundit",
)


def canonicalize_url(raw_url: str) -> str:
    """Strip tracking parameters and fragments to produce a clean canonical URL."""
    try:
        parsed = urlparse(raw_url.strip())
        if not parsed.scheme or not parsed.netloc:
            return ""

        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "ref", "gh_src", "source", "refId", "trackingId", "position", "pageNum",
            "f", "from", "trk", "tracking",
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
            "",
        ))
    except Exception:
        return raw_url.strip()


def is_candidate_url_structure(url: str) -> bool:
    """Preliminary URL structure check to eliminate obvious search aggregator pages."""
    parsed = urlparse(url.lower())
    netloc = parsed.netloc
    path = parsed.path
    query = parsed.query

    if any(dom in netloc for dom in EXCLUDED_DOMAINS):
        return False

    # Check for known ATS individual job URL patterns
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

    # Reject known search/category aggregator paths
    for pattern in AGGREGATOR_URL_PATTERNS:
        if re.search(pattern, path) or re.search(pattern, f"?{query}"):
            return False

    # Reject bare root domain or top-level /jobs or /careers
    if path in ("", "/", "/jobs", "/careers", "/jobs/", "/careers/"):
        return False

    return True


def _clean_html_text(html_fragment: str) -> str:
    """Clean HTML tags and normalize whitespace."""
    soup = BeautifulSoup(html_fragment, "html.parser")
    # Remove script and style elements
    for script in soup(["script", "style", "nav", "footer", "header"]):
        script.extract()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def _extract_from_json_ld(soup: BeautifulSoup, url: str) -> dict | None:
    """Extract JobPosting schema from JSON-LD scripts if present."""
    scripts = soup.find_all("script", type="application/ld+json")
    for s in scripts:
        if not s.string:
            continue
        try:
            data = json.loads(s.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type", "")
                if item_type == "JobPosting" or "JobPosting" in item_type:
                    title = item.get("title", "").strip()
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "").strip() if isinstance(org, dict) else str(org).strip()

                    # Extract location
                    loc_val = "Remote" if item.get("jobLocationType") == "TELECOMMUTE" else ""
                    job_loc = item.get("jobLocation", {})
                    if isinstance(job_loc, dict):
                        addr = job_loc.get("address", {})
                        if isinstance(addr, dict):
                            loc_parts = [
                                addr.get("addressLocality"),
                                addr.get("addressRegion"),
                                addr.get("addressCountry"),
                            ]
                            loc_val = ", ".join([p for p in loc_parts if p]) or loc_val
                        elif isinstance(addr, str):
                            loc_val = addr

                    desc = _clean_html_text(item.get("description", ""))
                    posted_at = item.get("datePosted", "")
                    job_id = str(item.get("identifier", {}).get("value") or "")

                    if title and company and desc:
                        return {
                            "title": title,
                            "company": company,
                            "location": loc_val or "Not Specified",
                            "description": desc,
                            "posted_at": posted_at,
                            "job_id": job_id,
                        }
        except Exception:
            continue
    return None


async def fetch_and_inspect_job_page(
    url: str,
    raw_title: str,
    default_role: str,
) -> dict | None:
    """Fetch the actual web page, inspect its content, and extract verified single-job data."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                logger.debug("Page fetch returned status %d for %s", resp.status_code, url)
                return None
            html_content = resp.text
    except Exception as exc:
        logger.debug("Could not fetch page for %s: %s", url, exc)
        return None

    soup = BeautifulSoup(html_content, "html.parser")
    page_text = _clean_html_text(html_content).lower()

    # 1. Multi-job aggregator detection in page content
    aggregator_content_signals = [
        r"\bshowing \d+[-–]\d+ of \d+ jobs\b",
        r"\b\d+[\+,\d]* jobs found\b",
        r"\bsearch results for\b",
        r"\bbrowse jobs by category\b",
        r"\btop \d+ careers\b",
        r"\binterview questions and answers\b",
    ]
    for pattern in aggregator_content_signals:
        if re.search(pattern, page_text):
            logger.debug("Page rejected as multi-job aggregator for %s: pattern '%s'", url, pattern)
            return None

    # 2. Check JSON-LD structured data first
    json_ld_data = _extract_from_json_ld(soup, url)
    if json_ld_data and len(json_ld_data["description"]) > 50:
        company = json_ld_data["company"]
        title = json_ld_data["title"]

        # Validate company is not fake/generic
        if not any(re.search(pat, company, re.IGNORECASE) for pat in GENERIC_COMPANY_PATTERNS):
            job_id = json_ld_data.get("job_id") or hashlib.sha256(url.encode()).hexdigest()[:16]
            return {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": json_ld_data["location"],
                "description": json_ld_data["description"][:3000],
                "application_url": url,
                "source": "tavily_verified",
                "posted_at": json_ld_data.get("posted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }

    # 3. HTML Element Extraction fallback
    # Check H1 / Title
    h1 = soup.find("h1")
    title_text = h1.get_text().strip() if h1 else raw_title

    # Exclude non-job title keywords
    if any(k in title_text.lower() for k in EXCLUDED_TITLE_KEYWORDS):
        return None

    # Extract company from OpenGraph site_name or title
    og_site = soup.find("meta", property="og:site_name")
    company_name = og_site.get("content", "").strip() if og_site else ""

    if not company_name:
        # ATS domain pattern (e.g. boards.greenhouse.io/stripe/jobs/123 -> Stripe)
        ats_match = re.search(r"(?:greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|workable\.com)/([^/]+)", url)
        if ats_match:
            company_name = ats_match.group(1).replace("-", " ").title()

    if not company_name:
        # Title parsing: "Role at Company" or "Company - Role"
        parts = [p.strip() for p in re.split(r"[-|–—:]", title_text) if p.strip()]
        if len(parts) >= 2:
            company_name = parts[0] if len(parts[0]) < len(parts[1]) else parts[1]

    # Validate company name
    if not company_name or any(re.search(pat, company_name, re.IGNORECASE) for pat in GENERIC_COMPANY_PATTERNS):
        return None

    # Extract location from common location selectors
    location = "Not Specified"
    loc_el = soup.find(class_=re.compile(r"location|job-location|workplace", re.IGNORECASE))
    if loc_el:
        loc_text = loc_el.get_text().strip()
        if len(loc_text) < 60:
            location = loc_text

    # Extract description from main content area
    desc_el = soup.find(class_=re.compile(r"job-description|description|content|posting-requirements", re.IGNORECASE))
    desc_text = _clean_html_text(str(desc_el)) if desc_el else page_text[:2000]

    if len(desc_text) < 80:
        return None

    job_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    return {
        "job_id": job_id,
        "title": title_text[:100],
        "company": company_name[:80],
        "location": location,
        "description": desc_text[:3000],
        "application_url": url,
        "source": "tavily_verified",
        "posted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


async def _search_tavily(
    role: str,
    skills: list[str],
    locations: list[str],
    experience_years: int,
    max_results: int,
) -> list[dict]:
    """Search Tavily for candidate URLs, fetch/inspect the actual web pages, and return verified jobs."""
    if not settings.tavily_api_key:
        return []

    try:
        from langchain_community.tools.tavily_search import TavilySearchResults

        loc_str = " OR ".join(locations) if locations else ""
        skills_str = " ".join(skills[:2]) if skills else ""

        queries = [
            f'"{role}" ({loc_str}) ("boards.greenhouse.io" OR "jobs.lever.co" OR "myworkdayjobs.com" OR "jobs.smartrecruiters.com" OR "jobs.ashbyhq.com")',
            f'"{role}" {skills_str} ("apply" OR "job description" OR "responsibilities") {loc_str}',
        ]

        candidate_urls: list[tuple[str, str]] = []
        seen_candidate_urls: set[str] = set()

        tool = TavilySearchResults(
            max_results=max(10, max_results + 5),
            tavily_api_key=settings.tavily_api_key,
        )

        for query in queries:
            try:
                results = tool.invoke({"query": query})
                if isinstance(results, list):
                    for r in results:
                        u = r.get("url", "").strip()
                        t = r.get("title", "").strip()
                        if u and u not in seen_candidate_urls:
                            canon = canonicalize_url(u)
                            if canon and is_candidate_url_structure(canon):
                                candidate_urls.append((canon, t))
                                seen_candidate_urls.add(canon)
            except Exception as e:
                logger.warning("Tavily query '%s' failed: %s", query, e)

        # Inspect candidate pages
        verified_jobs: list[dict] = []
        seen_signatures: set[tuple[str, str]] = set()

        for url, raw_title in candidate_urls:
            if len(verified_jobs) >= max_results:
                break

            job_data = await fetch_and_inspect_job_page(url, raw_title, role)
            if not job_data:
                continue

            # Strict deduplication by (normalized company, normalized title)
            norm_comp = re.sub(r"[^\w]", "", job_data["company"].lower())
            norm_title = re.sub(r"[^\w]", "", job_data["title"].lower())
            sig = (norm_comp, norm_title)

            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            verified_jobs.append(job_data)

        return verified_jobs
    except Exception as exc:
        logger.error("Error in Tavily job discovery pipeline: %s", exc)
        return []


async def search_jobs_tool(
    role: str,
    skills: list[str] | None = None,
    locations: list[str] | None = None,
    experience_years: int = 0,
    max_results: int = 30,
    test_mode: bool | None = None,
) -> str:
    """MCP tool implementation to search, inspect actual pages, validate, and return real individual job listings."""
    locations = locations or []
    skills = skills or []

    # Determine test mode
    is_test = settings.test_mode if test_mode is None else test_mode

    # If test mode is explicitly enabled, return deterministic mock jobs
    if is_test:
        logger.info("TEST_MODE active — returning mock jobs for test harness.")
        mock_subset = []
        for mock in MOCK_JOBS:
            loc_match = not locations or any(
                loc.lower() in mock["location"].lower() for loc in locations
            )
            if loc_match:
                mock_subset.append(mock)
        return json.dumps({
            "jobs": mock_subset[:max_results],
            "total_found": len(mock_subset[:max_results]),
            "status": "TEST_MOCK_DATA",
        })

    # Live Production Job Discovery
    if not settings.tavily_api_key:
        logger.warning("Tavily API key is not configured — live job search is unavailable.")
        return json.dumps({
            "jobs": [],
            "total_found": 0,
            "status": "LIVE_JOB_SEARCH_UNAVAILABLE",
            "message": "Tavily API key not configured in .env. Live job search is unavailable.",
        })

    jobs = await _search_tavily(
        role=role,
        skills=skills,
        locations=locations,
        experience_years=experience_years,
        max_results=max_results,
    )

    return json.dumps({
        "jobs": jobs,
        "total_found": len(jobs),
        "status": "SUCCESS" if jobs else "NO_MATCHING_JOBS_FOUND",
    })
