"""
MCP tool: search_jobs

Finds real individual job postings using Tavily, validates candidate URLs,
fetches job pages using fast HTTP, falls back to Playwright for JS-heavy
pages, and returns only verified individual job postings.

Pipeline:

Tavily
   ↓
Candidate URLs
   ↓
URL structure validation
   ↓
HTTP extraction
   ↓
Playwright fallback
   ↓
Job title validation
   ↓
Company validation
   ↓
Role validation
   ↓
Experience validation
   ↓
Deduplication
   ↓
Verified jobs
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


# ============================================================
# MOCK DATA
# ============================================================

MOCK_JOBS = [
    {
        "job_id": "mock-job-001",
        "title": "Senior Java Developer",
        "company": "Infosys",
        "location": "Pune",
        "description": (
            "Develop enterprise microservices using Java 17, Spring Boot, "
            "Microservices, PostgreSQL, and AWS. 3+ years experience required."
        ),
        "application_url": "https://careers.infosys.com/job/java-developer-pune",
        "source": "mock",
        "posted_at": "2026-08-15",
    },
    {
        "job_id": "mock-job-002",
        "title": "Java Backend Engineer",
        "company": "Tata Consultancy Services",
        "location": "Mumbai",
        "description": (
            "Build high-throughput microservices with Java 17, Spring Boot, "
            "REST APIs, Kafka, and PostgreSQL."
        ),
        "application_url": "https://careers.tcs.com/job/java-backend-mumbai",
        "source": "mock",
        "posted_at": "2026-08-14",
    },
    {
        "job_id": "mock-job-003",
        "title": "Full Stack Java Developer",
        "company": "Wipro",
        "location": "Bangalore",
        "description": (
            "Java, Spring Boot, React, AWS, Docker, Kubernetes. "
            "Designing scalable distributed cloud native web applications."
        ),
        "application_url": "https://careers.wipro.com/job/fullstack-java",
        "source": "mock",
        "posted_at": "2026-08-13",
    },
    {
        "job_id": "mock-job-004",
        "title": "Java Microservices Developer",
        "company": "Accenture",
        "location": "Pune",
        "description": (
            "Design and deploy cloud-native Java microservices on AWS and GCP "
            "with Kubernetes, Docker, and CI/CD pipelines."
        ),
        "application_url": "https://careers.accenture.com/job/java-microservices",
        "source": "mock",
        "posted_at": "2026-08-12",
    },
    {
        "job_id": "mock-job-005",
        "title": "Java Cloud Architect",
        "company": "Tech Mahindra",
        "location": "Mumbai",
        "description": (
            "Lead enterprise architecture for Java, Spring Boot, AWS, Kafka, "
            "Microservices, and Event-Driven systems. 5+ years experience."
        ),
        "application_url": "https://careers.techmahindra.com/job/java-architect",
        "source": "mock",
        "posted_at": "2026-08-10",
    },
]


# ============================================================
# DOMAIN / TITLE FILTERS
# ============================================================

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
    "top ai careers",
    "top careers",
    "best careers",
    "what is",
    "cheat sheet",
    "jobs in ",
    "+ jobs",
    "job vacancies in",
    "404",
    "not found",
    "page not found",
    "error",
)


SENIOR_TITLE_KEYWORDS = (
    "senior",
    "sr.",
    "sr ",
    "lead",
    "staff",
    "principal",
    "director",
    "manager",
    "vp",
    "head of",
    "architect",
    "chief",
    "team lead",
    "tech lead",
)


ROLE_SYNONYMS = {
    "ai developer": [
        "AI Developer",
        "AI Engineer",
        "Junior AI Engineer",
        "Machine Learning Engineer",
        "ML Engineer",
        "Generative AI Developer",
        "Generative AI Engineer",
        "GenAI Engineer",
        "LLM Engineer",
        "AI/ML Engineer",
        "Junior ML Engineer",
        "Python AI Developer",
        "Applied AI Engineer",
    ],
    "ai engineer": [
        "AI Engineer",
        "AI Developer",
        "Junior AI Engineer",
        "Machine Learning Engineer",
        "ML Engineer",
        "Generative AI Engineer",
        "GenAI Engineer",
        "LLM Engineer",
        "Applied AI Engineer",
    ],
    "machine learning engineer": [
        "Machine Learning Engineer",
        "ML Engineer",
        "AI Engineer",
        "AI Developer",
        "Junior ML Engineer",
        "Applied Machine Learning Engineer",
        "Python Machine Learning Engineer",
    ],
    "generative ai developer": [
        "Generative AI Developer",
        "Generative AI Engineer",
        "GenAI Engineer",
        "LLM Engineer",
        "AI Engineer",
        "AI Developer",
    ],
    "python developer": [
        "Python Developer",
        "Python Backend Developer",
        "Python Software Engineer",
        "Python AI Developer",
        "Junior Python Developer",
    ],
    "java developer": [
        "Java Developer",
        "Core Java Developer",
        "Java Backend Developer",
        "Java Software Engineer",
        "Junior Java Developer",
    ],
}


GENERIC_LISTING_TITLE_PATTERNS = (
    r"^[\w\s.-]+\s+(?:jobs|careers|vacancies|openings|opportunities)$",
    r"^(?:jobs|careers|openings|open positions|current openings|all jobs|work at|working at|join us)\s+.*$",
    r"^careers?\s*@\s*.*$",
    r"^jobs?\s+at\s+.*$",
    r"^(?:all\s+)?(?:open\s+)?(?:positions|roles|opportunities|vacancies)$",
    r"^careers?\s+portal$",
    r"^job\s+board$",
    r"^join\s+our\s+team$",
    r"^work\s+with\s+us$",
    r"^search\s+jobs?$",
)


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


GENERIC_COMPANY_PATTERNS = (
    # Numeric prefix (e.g. "10+ Openings", "50 Jobs")
    r"^\d+\+?\s*",
    # Generic words that indicate a listing page, not a real company
    # Use word boundaries so "Indeed Jobs" or "Remote Hiring" are caught
    r"\bjobs?\b",
    r"\bcareers?\b",
    r"\bhiring\b",
    r"\bremote\b",
    r"\bfresher\b",
    r"\bvacancies\b",
    r"\bopportunities\b",
    r"\bopenings?\b",
    # Exact-match for known non-companies
    r"^tech company$",
    r"^direct hire$",
    r"^direct employer$",
    r"^unknown$",
    r"^google search$",
    # Job board names (exact match — reject only when entire name is the board)
    r"^indeed$",
    r"^glassdoor$",
    r"^naukri$",
    r"^linkedin$",
    r"^hirist$",
    r"^monster$",
    r"^foundit$",
)


AGGREGATOR_CONTENT_SIGNALS = [
    r"\bshowing \d+[-–]\d+ of \d+ jobs\b",
    r"\b\d+[\+,\d]* jobs found\b",
    r"\bsearch results for\b",
    r"\bbrowse jobs by category\b",
    r"\btop \d+ careers\b",
    r"\binterview questions and answers\b",
    r"\bexplore\s+all\s+(?:openings|jobs|roles|positions)\b",
    r"\bsearch\s+(?:our\s+)?(?:open\s+)?(?:positions|jobs|openings)\b",
    r"\bfilter\s+by\s+(?:department|location|team)\b",
    r"\bview\s+all\s+(?:open\s+)?(?:positions|jobs|openings|roles)\b",
]


# ============================================================
# ROLE MATCHING
# ============================================================

def get_role_synonyms(role: str) -> list[str]:
    """Return semantic role equivalents."""
    r_clean = role.lower().strip()

    if r_clean in ROLE_SYNONYMS:
        return ROLE_SYNONYMS[r_clean]

    for key, synonyms in ROLE_SYNONYMS.items():
        if key in r_clean or r_clean in key:
            return synonyms

    return [role]


def is_role_compatible(job_title: str, target_role: str) -> bool:
    """
    Validate whether a job title is compatible with the target role.
    Also rejects generic listing/career titles.
    """

    if not target_role:
        return True

    title = job_title.lower().strip()
    target = target_role.lower().strip()

    # Generic listing pages
    if any(
        re.search(pattern, title)
        for pattern in GENERIC_LISTING_TITLE_PATTERNS
    ):
        logger.info(
            "TITLE REJECTED | generic listing title='%s'",
            job_title,
        )
        return False

    # Titles ending with jobs/careers/etc.
    if re.search(
        r"\b(?:jobs|careers|vacancies|openings|opportunities)$",
        title,
    ):
        role_indicators = (
            "developer",
            "engineer",
            "scientist",
            "architect",
            "analyst",
            "specialist",
            "programmer",
            "consultant",
            "intern",
            "associate",
            "lead",
        )

        if not any(word in title for word in role_indicators):
            logger.info(
                "TITLE REJECTED | listing-like title='%s'",
                job_title,
            )
            return False

    # Clearly unrelated roles
    unrelated = (
        "sales",
        "marketing",
        "accountant",
        "accounting",
        "recruiter",
        "talent acquisition",
        "human resources",
        "hr manager",
        "nurse",
        "physician",
        "pharmacist",
        "attorney",
        "legal counsel",
        "driver",
        "cashier",
        "clerk",
        "receptionist",
        "customer service representative",
    )

    if any(
        re.search(r"\b" + re.escape(word) + r"\b", title)
        for word in unrelated
    ):
        logger.info(
            "TITLE REJECTED | unrelated title='%s'",
            job_title,
        )
        return False

    # AI / ML role
    ai_target = any(
        word in target
        for word in (
            "ai",
            "machine learning",
            "ml",
            "genai",
            "generative",
            "deep learning",
            "nlp",
            "vision",
            "llm",
        )
    )

    if ai_target:
        ai_terms = (
            "ai",
            "artificial intelligence",
            "machine learning",
            "ml",
            "generative ai",
            "genai",
            "deep learning",
            "nlp",
            "computer vision",
            "llm",
            "data scientist",
            "data science",
            "applied ai",
            "python developer",
            "python engineer",
            "software engineer",
        )

        if any(
            re.search(r"\b" + re.escape(term) + r"\b", title)
            for term in ai_terms
        ):
            return True

        if "developer" in title or "engineer" in title:
            return True

        return False

    # General role matching
    target_words = [
        word
        for word in re.split(r"\W+", target)
        if len(word) > 2
    ]

    return any(word in title for word in target_words)


# ============================================================
# EXPERIENCE VALIDATION
# ============================================================

def is_experience_compatible(
    title: str,
    description: str,
    candidate_experience: int | None,
) -> tuple[bool, str]:
    """
    Validate experience requirements.

    For candidates with <=2 years:
    - Reject senior/lead titles.
    - Reject explicit 3+ year requirements.
    - Accept junior/entry-level/unspecified roles.
    """

    if candidate_experience is None:
        return True, "No candidate experience constraint"

    title_low = title.lower()
    description_low = description.lower()

    if candidate_experience <= 2:

        for keyword in SENIOR_TITLE_KEYWORDS:
            if re.search(
                r"\b" + re.escape(keyword) + r"\b",
                title_low,
            ):
                return (
                    False,
                    f"Senior role ('{keyword}') incompatible with "
                    f"{candidate_experience} year(s) experience",
                )

        matches = re.findall(
            r"(?:minimum|at least|require[s]?|with|have)\s+"
            r"([3-9]|1[0-5])\+?\s*(?:-\s*\d+)?\s*years?|"
            r"\b([3-9]|1[0-5])\+?\s*years?\s*"
            r"(?:of\s+)?(?:experience|exp|relevant)",
            description_low,
        )

        for match in matches:
            value = match[0] or match[1]

            if value and int(value) >= 3:
                return (
                    False,
                    f"Explicitly mandates {value}+ years experience "
                    f"(candidate has {candidate_experience} years)",
                )

    return True, "Experience level compatible"


# ============================================================
# SEARCH QUERY BUILDING
# ============================================================

def build_targeted_search_queries(
    role: str,
    skills: list[str],
    locations: list[str],
    experience_years: int,
) -> list[str]:
    """Build multiple high-precision job discovery queries."""

    ats_filter = (
        '("boards.greenhouse.io" OR '
        '"jobs.lever.co" OR '
        '"jobs.smartrecruiters.com" OR '
        '"jobs.ashbyhq.com" OR '
        '"apply.workable.com" OR '
        '"myworkdayjobs.com")'
    )

    loc_str = " OR ".join(locations[:3]) if locations else ""
    loc_clause = f"({loc_str})" if loc_str else ""

    synonyms = get_role_synonyms(role)

    queries: list[str] = []

    # Query 1: Exact target role
    role_terms = " OR ".join(
    f'"{item}"'
    for item in synonyms[:5]
)

    skill_terms = " OR ".join(
    f'"{skill}"'
    for skill in skills[:5]
    if skill and skill.strip()
)

    parts = [f"({role_terms})"]

    if skill_terms:
        parts.append(f"({skill_terms})")

    if loc_clause:
        parts.append(loc_clause)

    parts.append(ats_filter)

    queries.append(" ".join(parts))

    # Query 2: AI/ML + junior/entry level
    if experience_years <= 2:
        junior_terms = (
            '"Junior AI Engineer" OR '
            '"Junior Machine Learning Engineer" OR '
            '"AI Engineer" OR '
            '"ML Engineer" OR '
            '"Generative AI Engineer" OR '
            '"Python AI Engineer"'
        )

        parts = [f"({junior_terms})"]

        if loc_clause:
            parts.append(loc_clause)

        parts.append(ats_filter)

        queries.append(" ".join(parts))

    # Query 3: GenAI / LLM
    genai_terms = (
        '"Generative AI Engineer" OR '
        '"GenAI Engineer" OR '
        '"LLM Engineer" OR '
        '"AI/ML Engineer"'
    )

    parts = [f"({genai_terms})"]

    if loc_clause:
        parts.append(loc_clause)

    parts.append(ats_filter)

    queries.append(" ".join(parts))

    return queries


# ============================================================
# URL NORMALIZATION
# ============================================================

def canonicalize_url(raw_url: str) -> str:
    """Remove tracking parameters and fragments."""

    try:
        parsed = urlparse(raw_url.strip())

        if not parsed.scheme or not parsed.netloc:
            return ""

        tracking_params = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "ref",
            "gh_src",
            "source",
            "refId",
            "trackingId",
            "position",
            "pageNum",
            "f",
            "from",
            "trk",
            "tracking",
        }

        query_dict = parse_qs(parsed.query)

        cleaned_query = {
            key: value
            for key, value in query_dict.items()
            if key not in tracking_params
        }

        encoded_query = urlencode(
            cleaned_query,
            doseq=True,
        )

        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                parsed.params,
                encoded_query,
                "",
            )
        )

    except Exception:
        return raw_url.strip()


# ============================================================
# URL STRUCTURE VALIDATION
# ============================================================

def is_candidate_url_structure(url: str) -> bool:
    """
    Return True only when the URL looks like an individual job posting.

    Rejects:
    - company career pages
    - job catalog pages
    - search pages
    - aggregator pages
    - unsupported social/job platforms
    """

    try:
        parsed = urlparse(url.lower().strip())

        netloc = parsed.netloc
        path = parsed.path.rstrip("/")
        query = parsed.query

    except Exception:
        return False

    if not netloc:
        return False

    # Non-job domains
    if any(domain in netloc for domain in EXCLUDED_DOMAINS):
        return False

    # Aggregator/search URLs
    for pattern in AGGREGATOR_URL_PATTERNS:
        if re.search(pattern, path) or re.search(
            pattern,
            f"?{query}",
        ):
            return False

    # Common catalog roots
    if path in (
        "",
        "/",
        "/jobs",
        "/careers",
        "/openings",
        "/positions",
        "/vacancies",
        "/all-jobs",
        "/join-us",
        "/work-with-us",
    ):
        return False

    segments = [
        segment
        for segment in path.split("/")
        if segment
    ]

    # --------------------------------------------------------
    # Ashby
    # --------------------------------------------------------

    if "jobs.ashbyhq.com" in netloc:
        return len(segments) >= 2

    # --------------------------------------------------------
    # Lever
    # --------------------------------------------------------

    if "jobs.lever.co" in netloc:
        return len(segments) >= 2

    # --------------------------------------------------------
    # SmartRecruiters
    # --------------------------------------------------------

    if "jobs.smartrecruiters.com" in netloc:
        return len(segments) >= 2

    # --------------------------------------------------------
    # Greenhouse
    # --------------------------------------------------------

    if "greenhouse.io" in netloc:
        return bool(
            re.search(
                r"/jobs/[a-zA-Z0-9_-]+",
                path,
            )
            or "gh_jid=" in query
            or "token=" in query
        )

    # --------------------------------------------------------
    # Workday
    # --------------------------------------------------------

    if "myworkdayjobs.com" in netloc:
        return "/job/" in path

    # --------------------------------------------------------
    # Workable
    # --------------------------------------------------------

    if "workable.com" in netloc:
        return "/j/" in path

    # --------------------------------------------------------
    # BambooHR
    # --------------------------------------------------------

    if "bamboohr.com" in netloc:
        return bool(
            re.search(
                r"/(?:careers|jobs)/[a-zA-Z0-9_-]+",
                path,
            )
            or "id=" in query
        )

    # --------------------------------------------------------
    # Breezy HR
    # --------------------------------------------------------

    if "breezy.hr" in netloc:
        return "/p/" in path

    # --------------------------------------------------------
    # Rippling
    # --------------------------------------------------------

    if "rippling.com" in netloc:
        return bool(
            re.search(
                r"/[^/]+/jobs/[a-zA-Z0-9_-]+",
                path,
            )
        )

    # --------------------------------------------------------
    # Recruitee
    # --------------------------------------------------------

    if "recruitee.com" in netloc:
        return "/o/" in path

    # --------------------------------------------------------
    # Generic career sites
    # --------------------------------------------------------

    general_job_patterns = (
        r"/job/[a-zA-Z0-9_-]+",
        r"/jobs/[a-zA-Z0-9_-]+",
        r"/career/[a-zA-Z0-9_-]+",
        r"/careers/[a-zA-Z0-9_-]+",
        r"/position/[a-zA-Z0-9_-]+",
        r"/positions/[a-zA-Z0-9_-]+",
        r"/opening/[a-zA-Z0-9_-]+",
        r"/openings/[a-zA-Z0-9_-]+",
        r"/viewjob",
        r"/view/\d+",
        r"/details/\d+",
    )

    for pattern in general_job_patterns:
        if re.search(pattern, path):
            return True

    # One-segment generic pages are almost always catalogs.
    if len(segments) <= 1:
        return False

    return True


# ============================================================
# HTML HELPERS
# ============================================================

def _clean_html_text(html_fragment: str) -> str:
    """Remove HTML noise and normalize whitespace."""

    soup = BeautifulSoup(
        html_fragment,
        "html.parser",
    )

    for element in soup(
        [
            "script",
            "style",
            "nav",
            "footer",
            "header",
        ]
    ):
        element.extract()

    text = soup.get_text(separator=" ")

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _extract_from_json_ld(
    soup: BeautifulSoup,
    url: str ="",
) -> dict | None:
    """Extract schema.org JobPosting data."""

    scripts = soup.find_all(
        "script",
        type="application/ld+json",
    )

    for script in scripts:

        if not script.string:
            continue

        try:
            data = json.loads(script.string)

            items = (
                data
                if isinstance(data, list)
                else [data]
            )

            for item in items:

                if not isinstance(item, dict):
                    continue

                item_type = item.get("@type", "")

                if (
                    item_type != "JobPosting"
                    and "JobPosting" not in str(item_type)
                ):
                    continue

                title = str(
                    item.get("title") or ""
                ).strip()

                organization = item.get(
                    "hiringOrganization",
                    {},
                )

                if isinstance(organization, dict):
                    company = str(
                        organization.get("name") or ""
                    ).strip()
                else:
                    company = str(
                        organization or ""
                    ).strip()

                # Location
                location = ""

                if (
                    item.get("jobLocationType")
                    == "TELECOMMUTE"
                ):
                    location = "Remote"

                job_location = item.get(
                    "jobLocation",
                    {},
                )

                if isinstance(job_location, dict):

                    address = job_location.get(
                        "address",
                        {},
                    )

                    if isinstance(address, dict):

                        parts = [
                            address.get(
                                "addressLocality"
                            ),
                            address.get(
                                "addressRegion"
                            ),
                            address.get(
                                "addressCountry"
                            ),
                        ]

                        location = (
                            ", ".join(
                                str(part)
                                for part in parts
                                if part
                            )
                            or location
                        )

                    elif isinstance(address, str):
                        location = address

                description = _clean_html_text(
                    str(
                        item.get("description")
                        or ""
                    )
                )

                posted_at = str(
                    item.get("datePosted")
                    or ""
                )

                identifier = item.get(
                    "identifier",
                    {},
                )

                if isinstance(identifier, dict):
                    job_id = str(
                        identifier.get("value")
                        or ""
                    )
                else:
                    job_id = ""

                if (
                    title
                    and company
                    and description
                ):
                    return {
                        "title": title,
                        "company": company,
                        "location": location
                        or "Not Specified",
                        "description": description,
                        "posted_at": posted_at,
                        "job_id": job_id,
                    }

        except Exception:
            continue

    return None


# ============================================================
# JOB EXTRACTION
# ============================================================

def _extract_job_from_soup(
    soup: BeautifulSoup,
    url: str,
    raw_title: str,
    page_text: str,
    target_role: str = "",
    candidate_experience: int | None = None,
) -> dict | None:
    """
    Extract and validate one individual job posting.
    """

    # 1. URL validation
    if not is_candidate_url_structure(url):
        logger.info(
            "JOB REJECTED | invalid job URL | %s",
            url,
        )
        return None

    # 2. Aggregator content
    for pattern in AGGREGATOR_CONTENT_SIGNALS:

        if re.search(
            pattern,
            page_text,
        ):
            logger.info(
                "JOB REJECTED | aggregator content | %s",
                url,
            )
            return None

    # 3. JSON-LD
    json_ld = _extract_from_json_ld(soup)

    if (
        json_ld
        and len(json_ld["description"]) > 50
    ):

        title = json_ld["title"]
        company = json_ld["company"]
        description = json_ld["description"]

        if any(
            re.search(
                pattern,
                company,
                re.IGNORECASE,
            )
            for pattern in GENERIC_COMPANY_PATTERNS
        ):
            return None

        if not is_role_compatible(
            title,
            target_role,
        ):
            return None

        experience_ok, reason = (
            is_experience_compatible(
                title,
                description,
                candidate_experience,
            )
        )

        if not experience_ok:
            logger.info(
                "JOB REJECTED | experience | title='%s' | reason='%s'",
                title,
                reason,
            )
            return None

        job_id = (
            json_ld.get("job_id")
            or hashlib.sha256(
                url.encode()
            ).hexdigest()[:16]
        )

        return {
            "job_id": job_id,
            "title": title,
            "company": company,
            "location": json_ld["location"],
            "description": description[:3000],
            "application_url": url,
            "source": "tavily_verified",
            "posted_at": (
                json_ld.get("posted_at")
                or datetime.now(
                    timezone.utc
                ).strftime("%Y-%m-%d")
            ),
        }

    # 4. HTML title
    title_text = ""

    h1 = soup.find("h1")

    if h1:
        title_text = h1.get_text(
            strip=True
        )

    if not title_text:

        og_title = soup.find(
            "meta",
            property="og:title",
        )

        if og_title:
            title_text = (
                og_title.get(
                    "content",
                    "",
                ).strip()
            )

    if not title_text:

        title_element = soup.find("title")

        if title_element:
            title_text = title_element.get_text(
                strip=True
            )

    if not title_text:
        title_text = raw_title

    # Remove ATS suffixes
    title_text = re.sub(
        r"\s*\|\s*"
        r"(SmartRecruiters|Greenhouse|Lever|"
        r"Job Board|Workday).*$",
        "",
        title_text,
        flags=re.IGNORECASE,
    ).strip()

    if not title_text:
        return None

    # Generic title filters
    if any(
        keyword in title_text.lower()
        for keyword in EXCLUDED_TITLE_KEYWORDS
    ):
        logger.info(
            "JOB REJECTED | excluded title='%s'",
            title_text,
        )
        return None

    if not is_role_compatible(
        title_text,
        target_role,
    ):
        return None

    # 5. Company extraction
    company_name = ""

    og_site = soup.find(
        "meta",
        property="og:site_name",
    )

    if og_site:
        company_name = (
            og_site.get(
                "content",
                "",
            ).strip()
        )

    if not company_name:

        ats_match = re.search(
            r"(?:greenhouse\.io|"
            r"lever\.co|"
            r"ashbyhq\.com|"
            r"smartrecruiters\.com|"
            r"workable\.com)/([^/]+)",
            url,
        )

        if ats_match:
            company_name = (
                ats_match.group(1)
                .replace("-", " ")
                .title()
            )

    if not company_name:

        parts = [
            part.strip()
            for part in re.split(
                r"[-|–—:]",
                title_text,
            )
            if part.strip()
        ]

        if len(parts) >= 2:
            company_name = (
                parts[0]
                if len(parts[0])
                < len(parts[1])
                else parts[1]
            )

    if not company_name:
        return None

    # Generic company validation
    if any(
        re.search(
            pattern,
            company_name,
            re.IGNORECASE,
        )
        for pattern in GENERIC_COMPANY_PATTERNS
    ):
        logger.info(
            "JOB REJECTED | generic company='%s'",
            company_name,
        )
        return None

    # 6. Location
    location = "Not Specified"

    location_element = soup.find(
        class_=re.compile(
            r"location|job-location|workplace|city",
            re.IGNORECASE,
        )
    )

    if location_element:

        location_text = location_element.get_text(
            strip=True
        )

        if len(location_text) < 60:
            location = location_text

    # 7. Description
    description_element = soup.find(
        class_=re.compile(
            r"job-description|description|content|"
            r"posting-requirements|job-sections",
            re.IGNORECASE,
        )
    )

    if description_element:
        description = _clean_html_text(
            str(description_element)
        )
    else:
        description = page_text[:2000]

    if len(description) < 60:
        return None

    # 8. Experience
    experience_ok, reason = (
        is_experience_compatible(
            title_text,
            description,
            candidate_experience,
        )
    )

    if not experience_ok:
        logger.info(
            "JOB REJECTED | experience | title='%s' | reason='%s'",
            title_text,
            reason,
        )
        return None

    job_id = hashlib.sha256(
        url.encode()
    ).hexdigest()[:16]

    logger.info(
        "JOB VERIFIED | title='%s' | company='%s' | url='%s'",
        title_text,
        company_name,
        url,
    )

    return {
        "job_id": job_id,
        "title": title_text[:100],
        "company": company_name[:80],
        "location": location,
        "description": description[:3000],
        "application_url": url,
        "source": "tavily_verified",
        "posted_at": datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d"),
    }


# ============================================================
# PLAYWRIGHT
# ============================================================

async def _playwright_render_page(
    url: str,
) -> str | None:
    """Render JS-heavy pages using Playwright."""

    start_time = time.monotonic()

    logger.info(
        "PLAYWRIGHT START | %s",
        url,
    )

    try:
        from playwright.async_api import (
            async_playwright,
        )
    except ImportError:
        logger.warning(
            "Playwright is not installed."
        )
        return None

    try:

        async with async_playwright() as playwright:

            browser = await playwright.chromium.launch(
                headless=True,
            )

            context = await browser.new_context(
                viewport={
                    "width": 1280,
                    "height": 900,
                },
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/124.0.0.0 "
                    "Safari/537.36"
                ),
            )

            page = await context.new_page()

            try:

                await page.goto(
                    url,
                    timeout=6000,
                    wait_until="domcontentloaded",
                )

                await asyncio.sleep(0.5)

                html = await page.content()

                logger.info(
                    "PLAYWRIGHT SUCCESS | %.2fs | %s",
                    time.monotonic()
                    - start_time,
                    url,
                )

                return html

            except Exception as exc:

                logger.warning(
                    "PLAYWRIGHT FAILED | %.2fs | %s | %s",
                    time.monotonic()
                    - start_time,
                    url,
                    exc,
                )

                return None

            finally:
                await browser.close()

    except Exception as exc:

        logger.warning(
            "PLAYWRIGHT LAUNCH FAILED | %s",
            exc,
        )

        return None


# ============================================================
# PAGE FETCH + VALIDATION
# ============================================================

async def fetch_and_inspect_job_page(
    url: str,
    raw_title: str,
    default_role: str = "",
    candidate_experience: int | None = None,
) -> dict | None:
    """
    Fetch and validate one candidate job page.
    """

    # IMPORTANT:
    # Reject listing pages before making an HTTP request.
    if not is_candidate_url_structure(url):

        logger.info(
            "PAGE REJECTED BEFORE FETCH | %s",
            url,
        )

        return None

    start_time = time.monotonic()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/124.0.0.0 "
            "Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
    }

    html_content = None

    # --------------------------------------------------------
    # Fast HTTP
    # --------------------------------------------------------

    try:

        async with httpx.AsyncClient(
            timeout=6.0,
            follow_redirects=True,
            verify=False,
        ) as client:

            response = await client.get(
                url,
                headers=headers,
            )

            if response.status_code < 400:
                html_content = response.text

            elif response.status_code == 404:
                logger.info(
                    "PAGE 404 | %s",
                    url,
                )
                return None

    except Exception as exc:

        logger.debug(
            "HTTP FETCH FAILED | %s | %s",
            url,
            exc,
        )

    # --------------------------------------------------------
    # HTTP extraction
    # --------------------------------------------------------

    if html_content:

        soup = BeautifulSoup(
            html_content,
            "html.parser",
        )

        page_text = _clean_html_text(
            html_content
        ).lower()

        result = _extract_job_from_soup(
            soup=soup,
            url=url,
            raw_title=raw_title,
            page_text=page_text,
            target_role=default_role,
            candidate_experience=candidate_experience,
        )

        if result:

            logger.info(
                "HTTP VALIDATION SUCCESS | %.2fs | %s",
                time.monotonic()
                - start_time,
                url,
            )

            return result

        # If substantial HTML was returned and extraction
        # failed, don't automatically render every page.
        if len(html_content) > 1500:

            logger.info(
                "HTTP PAGE REJECTED | %.2fs | %s",
                time.monotonic()
                - start_time,
                url,
            )

            return None

    # --------------------------------------------------------
    # Playwright fallback
    # --------------------------------------------------------

    rendered_html = await _playwright_render_page(
        url
    )

    if rendered_html:

        soup = BeautifulSoup(
            rendered_html,
            "html.parser",
        )

        page_text = _clean_html_text(
            rendered_html
        ).lower()

        result = _extract_job_from_soup(
            soup=soup,
            url=url,
            raw_title=raw_title,
            page_text=page_text,
            target_role=default_role,
            candidate_experience=candidate_experience,
        )

        if result:

            result["source"] = (
                "tavily_playwright_verified"
            )

            logger.info(
                "PLAYWRIGHT VALIDATION SUCCESS | %.2fs | %s",
                time.monotonic()
                - start_time,
                url,
            )

            return result

    logger.info(
        "PAGE VALIDATION FAILED | %.2fs | %s",
        time.monotonic()
        - start_time,
        url,
    )

    return None


# ============================================================
# TAVILY SEARCH
# ============================================================

async def _search_tavily(
    role: str,
    skills: list[str],
    locations: list[str],
    experience_years: int,
    max_results: int,
) -> list[dict]:
    """
    Search Tavily using multiple targeted queries and
    validate the resulting URLs/pages.
    """

    if not settings.tavily_api_key:

        logger.warning(
            "Tavily API key is not configured."
        )

        return []

    try:

        from langchain_community.tools.tavily_search import (
            TavilySearchResults,
        )

        queries = build_targeted_search_queries(
            role=role,
            skills=skills,
            locations=locations,
            experience_years=experience_years,
        )

        logger.info(
            "TAVILY QUERY COUNT | %d",
            len(queries),
        )

        candidate_urls: list[
            tuple[str, str]
        ] = []

        seen_candidate_urls: set[str] = set()

        search_start = time.monotonic()

        tool = TavilySearchResults(
            max_results=min(
                max(max_results, 8),
                10,
            ),
            tavily_api_key=settings.tavily_api_key,
        )

        loop = asyncio.get_running_loop()

        # ----------------------------------------------------
        # Execute targeted queries
        # ----------------------------------------------------

        for query_index, query in enumerate(
            queries,
            start=1,
        ):

            logger.info(
                "TAVILY START | query=%d/%d | %s",
                query_index,
                len(queries),
                query,
            )

            try:

                results = await loop.run_in_executor(
                    None,
                    lambda q=query: tool.invoke(
                        {"query": q}
                    ),
                )

                if not isinstance(
                    results,
                    list,
                ):
                    continue

                for result in results:

                    url = (
                        result.get("url", "")
                        .strip()
                    )

                    title = (
                        result.get("title", "")
                        .strip()
                    )

                    if not url:
                        continue

                    canonical_url = (
                        canonicalize_url(url)
                    )

                    if not canonical_url:
                        continue

                    if (
                        canonical_url
                        in seen_candidate_urls
                    ):
                        continue

                    # IMPORTANT:
                    # Reject listing/catalog URLs
                    # immediately.
                    if not is_candidate_url_structure(
                        canonical_url
                    ):

                        logger.info(
                            "CANDIDATE REJECTED | invalid URL | title='%s' | url='%s'",
                            title,
                            canonical_url,
                        )

                        continue

                    logger.info(
                        "CANDIDATE ACCEPTED | title='%s' | url='%s'",
                        title,
                        canonical_url,
                    )

                    candidate_urls.append(
                        (
                            canonical_url,
                            title,
                        )
                    )

                    seen_candidate_urls.add(
                        canonical_url
                    )

            except Exception as exc:

                logger.warning(
                    "TAVILY QUERY FAILED | query=%d | %s",
                    query_index,
                    exc,
                )

        logger.info(
            "TAVILY END | %.2fs | candidates=%d",
            time.monotonic()
            - search_start,
            len(candidate_urls),
        )

        # ----------------------------------------------------
        # Validate pages concurrently
        # ----------------------------------------------------

        validation_start = time.monotonic()

        semaphore = asyncio.Semaphore(3)

        async def validate_candidate(
            url: str,
            title: str,
        ) -> dict | None:

            async with semaphore:

                try:

                    return await asyncio.wait_for(
                        fetch_and_inspect_job_page(
                            url=url,
                            raw_title=title,
                            default_role=role,
                            candidate_experience=experience_years,
                        ),
                        timeout=8.0,
                    )

                except asyncio.TimeoutError:

                    logger.warning(
                        "VALIDATION TIMEOUT | %s",
                        url,
                    )

                    return None

                except Exception as exc:

                    logger.debug(
                        "VALIDATION ERROR | %s | %s",
                        url,
                        exc,
                    )

                    return None

        tasks = [
            validate_candidate(
                url,
                title,
            )
            for url, title in candidate_urls[
                :max(20, max_results)
            ]
        ]

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        # ----------------------------------------------------
        # Deduplicate verified jobs
        # ----------------------------------------------------

        verified_jobs: list[dict] = []

        seen_signatures: set[
            tuple[str, str]
        ] = set()

        for result in results:

            if not isinstance(
                result,
                dict,
            ):
                continue

            if not result:
                continue

            company = re.sub(
                r"[^\w]",
                "",
                result["company"].lower(),
            )

            title = re.sub(
                r"[^\w]",
                "",
                result["title"].lower(),
            )

            signature = (
                company,
                title,
            )

            if signature in seen_signatures:
                continue

            seen_signatures.add(
                signature
            )

            verified_jobs.append(
                result
            )

        logger.info(
            "VALIDATION END | %.2fs | "
            "candidates=%d | verified=%d",
            time.monotonic()
            - validation_start,
            len(candidate_urls),
            len(verified_jobs),
        )

        # Return only requested number
        return verified_jobs[:max_results]

    except Exception as exc:

        logger.exception(
            "TAVILY PIPELINE ERROR | %s",
            exc,
        )

        return []


# ============================================================
# MCP TOOL
# ============================================================

async def search_jobs_tool(
    role: str,
    skills: list[str] | None = None,
    locations: list[str] | None = None,
    experience_years: int = 0,
    max_results: int = 30,
    test_mode: bool | None = None,
) -> str:
    """
    MCP search_jobs tool.

    Returns only verified individual job postings.
    """

    start_time = time.monotonic()

    skills = skills or []
    locations = locations or []

    logger.info(
        "=" * 70
    )

    logger.info(
        "SEARCH_JOBS START | role='%s' | "
        "experience=%s | locations=%s | max_results=%s",
        role,
        experience_years,
        locations,
        max_results,
    )

    # --------------------------------------------------------
    # Test mode
    # --------------------------------------------------------

    is_test = (
        settings.test_mode
        if test_mode is None
        else test_mode
    )

    if is_test:

        logger.info(
            "TEST_MODE active."
        )

        mock_jobs = []

        for job in MOCK_JOBS:

            location_match = (
                not locations
                or any(
                    location.lower()
                    in job["location"].lower()
                    for location in locations
                )
            )

            if location_match:
                mock_jobs.append(job)

        jobs = mock_jobs[:max_results]

        logger.info(
            "SEARCH_JOBS END | "
            "status=TEST_MOCK_DATA | jobs=%d | %.2fs",
            len(jobs),
            time.monotonic()
            - start_time,
        )

        return json.dumps(
            {
                "jobs": jobs,
                "total_found": len(jobs),
                "status": "TEST_MOCK_DATA",
            }
        )

    # --------------------------------------------------------
    # Production API key check
    # --------------------------------------------------------

    if not settings.tavily_api_key:

        logger.warning(
            "Tavily API key is not configured."
        )

        return json.dumps(
            {
                "jobs": [],
                "total_found": 0,
                "status": "LIVE_JOB_SEARCH_UNAVAILABLE",
                "message": (
                    "Tavily API key not configured "
                    "in .env."
                ),
            }
        )

    # --------------------------------------------------------
    # Live search
    # --------------------------------------------------------

    jobs = await _search_tavily(
        role=role,
        skills=skills,
        locations=locations,
        experience_years=experience_years,
        max_results=max_results,
    )

    status = (
        "SUCCESS"
        if jobs
        else "NO_MATCHING_JOBS_FOUND"
    )

    elapsed = (
        time.monotonic()
        - start_time
    )

    logger.info(
        "SEARCH_JOBS END | status=%s | jobs=%d | %.2fs",
        status,
        len(jobs),
        elapsed,
    )

    logger.info(
        "=" * 70
    )

    return json.dumps(
        {
            "jobs": jobs,
            "total_found": len(jobs),
            "status": status,
        }
    )