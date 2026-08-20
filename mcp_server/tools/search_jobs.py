"""MCP tool: search_jobs — fetches, inspects, validates, and extracts individual job postings.

Includes fast async HTTP extraction, strict URL/job validation, structured timing logging,
parallel verification, and Playwright fallback with finite timeouts.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
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

# Senior/Lead keywords to reject when candidate experience <= 2 years
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

# Semantic role equivalents
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


def get_role_synonyms(role: str) -> list[str]:
    """Retrieve semantic equivalents for a given job role."""
    r_clean = role.lower().strip()
    if r_clean in ROLE_SYNONYMS:
        return ROLE_SYNONYMS[r_clean]
    for k, syns in ROLE_SYNONYMS.items():
        if k in r_clean or r_clean in k:
            return syns
    return [role]


def is_role_compatible(job_title: str, target_role: str) -> bool:
    """Semantic role compatibility check. Rejects generic company listing/career page titles."""
    if not target_role:
        return True
    t_low = target_role.lower().strip()
    j_low = job_title.lower().strip()

    # 1. Reject generic company listing/career titles (e.g. "Wisdom AI Jobs", "Google Careers", "Open Positions")
    if any(re.search(pat, j_low) for pat in GENERIC_LISTING_TITLE_PATTERNS):
        return False

    # 2. Reject titles ending in "jobs", "careers", "openings", "vacancies" unless an explicit tech role word is present
    if re.search(r"\b(?:jobs|careers|vacancies|openings|opportunities)$", j_low):
        role_indicators = ["developer", "engineer", "scientist", "architect", "analyst", "specialist", "programmer", "consultant", "intern", "associate", "lead"]
        if not any(r in j_low for r in role_indicators):
            return False

    # 3. Reject obvious non-tech / completely unrelated titles
    unrelated = [
        "sales", "marketing", "accountant", "accounting", "recruiter", "talent acquisition",
        "human resources", "hr manager", "nurse", "physician", "pharmacist", "attorney",
        "legal counsel", "driver", "cashier", "clerk", "receptionist", "customer service representative",
    ]
    if any(re.search(r"\b" + re.escape(u) + r"\b", j_low) for u in unrelated):
        return False

    # AI / ML target role matching
    ai_synonyms = [
        "ai", "artificial intelligence", "machine learning", "ml", "generative ai",
        "genai", "deep learning", "nlp", "computer vision", "llm", "data scientist",
        "data science", "applied ai", "python developer", "python engineer", "software engineer",
    ]
    if any(s in t_low for s in ["ai", "machine learning", "ml", "genai", "generative", "deep learning", "nlp", "vision", "llm"]):
        if any(re.search(r"\b" + re.escape(s) + r"\b", j_low) for s in ai_synonyms) or "developer" in j_low or "engineer" in j_low:
            return True
        return False

    # General tech role matching
    target_words = [w for w in re.split(r"\W+", t_low) if len(w) > 2]
    if any(w in j_low for w in target_words):
        return True
    return True


def is_experience_compatible(title: str, description: str, candidate_experience: int | None) -> tuple[bool, str]:
    """Check experience compatibility.
    
    If candidate has <= 2 years experience (e.g. 1 year):
    - Reject senior/lead titles.
    - Reject jobs explicitly requiring 3+, 4+, 5+ years.
    - Accept 0-1, 0-2, 1-2, 1+, Junior, Entry-level, or unspecified experience.
    """
    if candidate_experience is None:
        return True, "No candidate experience constraint"

    t_low = title.lower()
    d_low = description.lower()

    if candidate_experience <= 2:
        # Check Senior Titles
        for kw in SENIOR_TITLE_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", t_low):
                return False, f"Senior role ('{kw}') incompatible with {candidate_experience} year(s) experience"

        # Check Explicit Experience Requirements in Description
        exp_req_matches = re.findall(
            r"(?:minimum|at least|require[s]?|with|have)\s+([3-9]|1[0-5])\+?\s*(?:-\s*\d+)?\s*years?|"
            r"\b([3-9]|1[0-5])\+?\s*years?\s*(?:of\s+)?(?:experience|exp|relevant)",
            d_low,
        )
        for m in exp_req_matches:
            val = m[0] or m[1]
            if val and int(val) >= 3:
                return False, f"Explicitly mandates {val}+ years experience (candidate has {candidate_experience} years)"

    return True, "Experience level compatible"


def build_targeted_search_queries(
    role: str,
    skills: list[str],
    locations: list[str],
    experience_years: int,
) -> list[str]:
    """Build targeted, high-precision search queries from user preferences."""
    ats_filter = '("boards.greenhouse.io" OR "jobs.lever.co" OR "jobs.smartrecruiters.com" OR "jobs.ashbyhq.com" OR "apply.workable.com" OR "myworkdayjobs.com")'
    loc_str = " OR ".join(locations[:3]) if locations else ""
    loc_clause = f"({loc_str})" if loc_str else ""

    role_syns = get_role_synonyms(role)
    role_syns_str = " OR ".join(f'"{r}"' for r in role_syns[:4])

    skill_terms = [f'"{s}"' if " " in s else s for s in skills[:3] if s]
    skill_clause = f"({' OR '.join(skill_terms)})" if skill_terms else ""

    queries = []

    # Query 1: Targeted Role Synonyms + Location + ATS domains + Top Skills
    q1_parts = [f"({role_syns_str})"]
    if loc_clause:
        q1_parts.append(loc_clause)
    if skill_clause:
        q1_parts.append(skill_clause)
    q1_parts.append(ats_filter)
    queries.append(" ".join(q1_parts))

    # Query 2: Experience-targeted query for entry/junior level
    if experience_years <= 2:
        exp_terms = '("Junior AI" OR "Junior Machine Learning" OR "AI Engineer" OR "Generative AI Developer" OR "Python AI Developer")'
        q2_parts = [exp_terms]
        if loc_clause:
            q2_parts.append(loc_clause)
        if skill_clause:
            q2_parts.append(skill_clause)
        q2_parts.append(ats_filter)
        queries.append(" ".join(q2_parts))

    return queries


# Patterns indicating generic company listing/career pages (NOT single job titles)
GENERIC_LISTING_TITLE_PATTERNS = (
    r"^[\w\s.-]+\s+(?:jobs|careers|vacancies|openings|opportunities)$",  # e.g. "Wisdom AI Jobs", "Google Careers"
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

# Aggregator content signals detected in page body
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
    """Validate whether URL represents an individual job posting vs a company listing / career page.
    
    Returns True ONLY for specific single-job URLs. Rejects company-level career/listing pages across:
    - Ashby (jobs.ashbyhq.com)
    - Lever (jobs.lever.co)
    - Greenhouse (boards.greenhouse.io)
    - Workday (*.myworkdayjobs.com)
    - SmartRecruiters (jobs.smartrecruiters.com)
    - Workable (apply.workable.com)
    - BambooHR (*.bamboohr.com)
    - Breezy HR (*.breezy.hr)
    - Rippling (ats.rippling.com)
    - Recruitee (*.recruitee.com)
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

    # 1. Non-job excluded domains
    if any(dom in netloc for dom in EXCLUDED_DOMAINS):
        return False

    # 2. Reject known search/category aggregator paths & queries
    for pattern in AGGREGATOR_URL_PATTERNS:
        if re.search(pattern, path) or re.search(pattern, f"?{query}"):
            return False

    # 3. Reject bare root domain or top-level /jobs or /careers
    if path in ("", "/", "/jobs", "/careers", "/openings", "/positions", "/vacancies", "/all-jobs", "/join-us", "/work-with-us"):
        return False

    segments = [s for s in path.split("/") if s]

    # 4. ATS Provider-Specific Checks for Company Listing vs Individual Job URL

    # Ashby (jobs.ashbyhq.com):
    # - Company listing: https://jobs.ashbyhq.com/<company> (1 segment)
    # - Individual job: https://jobs.ashbyhq.com/<company>/<job_id> (>= 2 segments)
    if "jobs.ashbyhq.com" in netloc or "ashbyhq.com" in netloc:
        if len(segments) < 2:
            return False
        return True

    # Lever (jobs.lever.co):
    # - Company listing: https://jobs.lever.co/<company> (1 segment)
    # - Individual job: https://jobs.lever.co/<company>/<job_id> (>= 2 segments)
    if "jobs.lever.co" in netloc or "lever.co" in netloc:
        if len(segments) < 2:
            return False
        return True

    # SmartRecruiters (jobs.smartrecruiters.com):
    # - Company listing: https://jobs.smartrecruiters.com/<company> (1 segment)
    # - Individual job: https://jobs.smartrecruiters.com/<company>/<job_id_or_slug> (>= 2 segments)
    if "jobs.smartrecruiters.com" in netloc or "smartrecruiters.com" in netloc:
        if len(segments) < 2:
            return False
        return True

    # Greenhouse (boards.greenhouse.io, job-boards.greenhouse.io):
    # - Company listing: https://boards.greenhouse.io/<company> or /<company>/jobs
    # - Individual job: https://boards.greenhouse.io/<company>/jobs/<job_id>
    if "greenhouse.io" in netloc:
        if not re.search(r"/jobs/[a-zA-Z0-9_-]+", path) and "token=" not in query and "gh_jid=" not in query:
            return False
        return True

    # Workday (*.myworkdayjobs.com):
    # - Company listing: https://tenant.wd12.myworkdayjobs.com/en-US/Site (no /job/)
    # - Individual job: https://tenant.wd12.myworkdayjobs.com/en-US/Site/job/Job-Title_JR123
    if "myworkdayjobs.com" in netloc:
        if "/job/" not in path:
            return False
        return True

    # Workable (apply.workable.com):
    # - Company listing: https://apply.workable.com/<company> (no /j/)
    # - Individual job: https://apply.workable.com/<company>/j/<job_id>
    if "workable.com" in netloc:
        if "/j/" not in path:
            return False
        return True

    # BambooHR (*.bamboohr.com):
    # - Company listing: https://company.bamboohr.com/careers
    # - Individual job: https://company.bamboohr.com/careers/<job_id>
    if "bamboohr.com" in netloc:
        if not re.search(r"/(?:careers|jobs)/[a-zA-Z0-9_-]+", path) and "id=" not in query:
            return False
        return True

    # Breezy HR (*.breezy.hr):
    # - Company listing: https://company.breezy.hr
    # - Individual job: https://company.breezy.hr/p/<job_id>
    if "breezy.hr" in netloc:
        if "/p/" not in path:
            return False
        return True

    # Rippling (ats.rippling.com):
    # - Company listing: https://ats.rippling.com/<company>/jobs
    # - Individual job: https://ats.rippling.com/<company>/jobs/<job_id>
    if "rippling.com" in netloc:
        if not re.search(r"/[^/]+/jobs/[a-zA-Z0-9_-]+", path):
            return False
        return True

    # Recruitee (*.recruitee.com):
    # - Company listing: https://company.recruitee.com
    # - Individual job: https://company.recruitee.com/o/<slug>
    if "recruitee.com" in netloc:
        if "/o/" not in path:
            return False
        return True

    # 5. General Career Site Checks
    # Common individual job path patterns
    general_job_patterns = [
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
    ]
    for pattern in general_job_patterns:
        if re.search(pattern, path):
            return True

    # If URL path has only 1 segment (e.g. /careers or /company-name) on non-ATS site, reject
    if len(segments) <= 1:
        return False

    return True


def _clean_html_text(html_fragment: str) -> str:
    """Clean HTML tags and normalize whitespace."""
    soup = BeautifulSoup(html_fragment, "html.parser")
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
                if item_type == "JobPosting" or "JobPosting" in str(item_type):
                    title = str(item.get("title") or "").strip()
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

                    desc = _clean_html_text(str(item.get("description") or ""))
                    posted_at = str(item.get("datePosted") or "")
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


def _extract_job_from_soup(
    soup: BeautifulSoup,
    url: str,
    raw_title: str,
    page_text: str,
    target_role: str = "",
    candidate_experience: int | None = None,
) -> dict | None:
    """Extract job data from parsed HTML soup with role & experience validation."""
    # 0. Reject company listing / career URLs
    if not is_candidate_url_structure(url):
        logger.debug("Page rejected as company listing / career URL: %s", url)
        return None

    # 1. Multi-job aggregator detection in page content
    for pattern in AGGREGATOR_CONTENT_SIGNALS:
        if re.search(pattern, page_text):
            logger.debug("Page rejected as multi-job aggregator for %s: pattern '%s'", url, pattern)
            return None

    # 2. Check JSON-LD structured data first
    json_ld_data = _extract_from_json_ld(soup, url)
    if json_ld_data and len(json_ld_data["description"]) > 50:
        company = json_ld_data["company"]
        title = json_ld_data["title"]
        desc = json_ld_data["description"]

        if not any(re.search(pat, company, re.IGNORECASE) for pat in GENERIC_COMPANY_PATTERNS):
            if is_role_compatible(title, target_role):
                exp_ok, exp_reason = is_experience_compatible(title, desc, candidate_experience)
                if exp_ok:
                    job_id = json_ld_data.get("job_id") or hashlib.sha256(url.encode()).hexdigest()[:16]
                    return {
                        "job_id": job_id,
                        "title": title,
                        "company": company,
                        "location": json_ld_data["location"],
                        "description": desc[:3000],
                        "application_url": url,
                        "source": "tavily_verified",
                        "posted_at": json_ld_data.get("posted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    }
                else:
                    logger.debug("JSON-LD job '%s' rejected by experience: %s", title, exp_reason)
            else:
                logger.debug("JSON-LD job '%s' rejected: incompatible with target role '%s'", title, target_role)

    # 3. HTML Element Extraction
    h1 = soup.find("h1")
    title_text = ""
    if h1 and h1.get_text().strip():
        title_text = h1.get_text().strip()
    if not title_text:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content", "").strip():
            title_text = og_title.get("content", "").strip()
    if not title_text:
        title_el = soup.find("title")
        if title_el and title_el.get_text().strip():
            title_text = title_el.get_text().strip()
    if not title_text:
        title_text = raw_title

    # Clean site suffix from title
    title_text = re.sub(r"\s*\|\s*(SmartRecruiters|Greenhouse|Lever|Job Board|Workday).*$", "", title_text, flags=re.IGNORECASE).strip()

    # Exclude non-job title keywords
    if not title_text or any(k in title_text.lower() for k in EXCLUDED_TITLE_KEYWORDS):
        return None

    # Role compatibility check
    if not is_role_compatible(title_text, target_role):
        logger.debug("Job title '%s' rejected: incompatible with role '%s'", title_text, target_role)
        return None

    # Extract company from OpenGraph site_name or title
    og_site = soup.find("meta", property="og:site_name")
    company_name = og_site.get("content", "").strip() if og_site else ""

    if not company_name:
        ats_match = re.search(r"(?:greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|workable\.com)/([^/]+)", url)
        if ats_match:
            company_name = ats_match.group(1).replace("-", " ").title()

    if not company_name:
        parts = [p.strip() for p in re.split(r"[-|–—:]", title_text) if p.strip()]
        if len(parts) >= 2:
            company_name = parts[0] if len(parts[0]) < len(parts[1]) else parts[1]

    # Validate company name
    if not company_name or any(re.search(pat, company_name, re.IGNORECASE) for pat in GENERIC_COMPANY_PATTERNS):
        return None

    # Extract location
    location = "Not Specified"
    loc_el = soup.find(class_=re.compile(r"location|job-location|workplace|city", re.IGNORECASE))
    if loc_el:
        loc_text = loc_el.get_text().strip()
        if len(loc_text) < 60:
            location = loc_text

    # Extract description
    desc_el = soup.find(class_=re.compile(r"job-description|description|content|posting-requirements|job-sections", re.IGNORECASE))
    desc_text = _clean_html_text(str(desc_el)) if desc_el else page_text[:2000]

    if len(desc_text) < 60:
        return None

    # Experience compatibility check
    exp_ok, exp_reason = is_experience_compatible(title_text, desc_text, candidate_experience)
    if not exp_ok:
        logger.debug("Job '%s' rejected by experience: %s", title_text, exp_reason)
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


async def _playwright_render_page(url: str) -> str | None:
    """Render a JavaScript-heavy page using Playwright with finite timeout.
    
    Used as fallback only when HTTP extraction is insufficient.
    """
    start_time = time.monotonic()
    logger.info("PLAYWRIGHT START: %s", url)
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.debug("Playwright not available for JS rendering fallback")
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                await page.goto(url, timeout=6000, wait_until="domcontentloaded")
                await asyncio.sleep(0.5)
                html_content = await page.content()
                elapsed = time.monotonic() - start_time
                logger.info("PLAYWRIGHT END: %s in %.2fs (length: %d)", url, elapsed, len(html_content))
                return html_content
            except Exception as exc:
                elapsed = time.monotonic() - start_time
                logger.warning("PLAYWRIGHT END (FAILED/TIMEOUT): %s in %.2fs (%s)", url, elapsed, exc)
                return None
            finally:
                await browser.close()
    except Exception as exc:
        elapsed = time.monotonic() - start_time
        logger.warning("PLAYWRIGHT LAUNCH FAILED: %s in %.2fs (%s)", url, elapsed, exc)
        return None


async def fetch_and_inspect_job_page(
    url: str,
    raw_title: str,
    default_role: str = "",
    candidate_experience: int | None = None,
) -> dict | None:
    """Fetch the actual web page, inspect its content, and extract verified single-job data."""
    if not is_candidate_url_structure(url):
        logger.debug("URL rejected prior to fetch as company listing/career page: %s", url)
        return None

    t0 = time.monotonic()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    html_content = None
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code < 400:
                html_content = resp.text
            elif resp.status_code == 404:
                return None
    except Exception as exc:
        logger.debug("HTTP fetch failed for %s: %s", url, exc)

    # 1. Try extracting from fast HTTP response
    if html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        page_text = _clean_html_text(html_content).lower()
        result = _extract_job_from_soup(
            soup, url, raw_title, page_text,
            target_role=default_role,
            candidate_experience=candidate_experience,
        )
        if result:
            elapsed = time.monotonic() - t0
            logger.info("URL VALIDATION [HTTP SUCCESS]: %s -> '%s' at '%s' (%.2fs)", url, result['title'], result['company'], elapsed)
            return result
        if len(html_content) > 1500:
            elapsed = time.monotonic() - t0
            logger.debug("URL VALIDATION [REJECTED]: %s in %.2fs", url, elapsed)
            return None

    # 2. Try Playwright fallback only for empty/minimal JS shells or failed HTTP
    rendered_html = await _playwright_render_page(url)
    if rendered_html:
        soup = BeautifulSoup(rendered_html, "html.parser")
        page_text = _clean_html_text(rendered_html).lower()
        result = _extract_job_from_soup(
            soup, url, raw_title, page_text,
            target_role=default_role,
            candidate_experience=candidate_experience,
        )
        if result:
            result["source"] = "tavily_playwright_verified"
            elapsed = time.monotonic() - t0
            logger.info("URL VALIDATION [PLAYWRIGHT SUCCESS]: %s -> '%s' at '%s' (%.2fs)", url, result['title'], result['company'], elapsed)
            return result

    elapsed = time.monotonic() - t0
    logger.debug("URL VALIDATION [REJECTED]: %s in %.2fs", url, elapsed)
    return None


async def _search_tavily(
    role: str,
    skills: list[str],
    locations: list[str],
    experience_years: int,
    max_results: int,
) -> list[dict]:
    """Search Tavily with targeted queries, fetch/inspect in parallel, and return verified jobs."""
    has_key = bool(settings.tavily_api_key)
    logger.info("TAVILY_API_KEY configured: %s", has_key)
    if not has_key:
        return []

    try:
        from langchain_community.tools.tavily_search import TavilySearchResults

        queries = build_targeted_search_queries(
            role=role,
            skills=skills,
            locations=locations,
            experience_years=experience_years,
        )

        candidate_urls: list[tuple[str, str]] = []
        seen_candidate_urls: set[str] = set()

        tavily_start = time.monotonic()
        tool = TavilySearchResults(
            max_results=min(max(max_results, 6), 10),
            tavily_api_key=settings.tavily_api_key,
        )

        loop = asyncio.get_running_loop()

        for q in queries[:2]:
            logger.info("TAVILY START: query='%s'", q)
            try:
                results = await loop.run_in_executor(None, lambda query=q: tool.invoke({"query": query}))
                if isinstance(results, list):
                    for r in results:
                        u = r.get("url", "").strip()
                        t = r.get("title", "").strip()
                        if u and u not in seen_candidate_urls:
                            canon = canonicalize_url(u)
                            if canon and is_candidate_url_structure(canon):
                                candidate_urls.append((canon, t))
                                seen_candidate_urls.add(canon)
            except Exception as q_err:
                logger.warning("Tavily query failed: '%s': %s", q, q_err)

        tavily_elapsed = time.monotonic() - tavily_start
        logger.info("TAVILY END: %.2fs (candidate URLs collected: %d)", tavily_elapsed, len(candidate_urls))

        logger.info("URL VALIDATION START: %d candidate URLs to validate", len(candidate_urls))
        val_start = time.monotonic()

        sem = asyncio.Semaphore(3)

        async def validate_with_sem(url: str, raw_title: str) -> dict | None:
            async with sem:
                try:
                    try:
                        return await asyncio.wait_for(
                            fetch_and_inspect_job_page(
                                url=url,
                                raw_title=raw_title,
                                default_role=role,
                                candidate_experience=experience_years,
                            ),
                            timeout=8.0,
                        )
                    except TypeError:
                        return await asyncio.wait_for(
                            fetch_and_inspect_job_page(url, raw_title, role),
                            timeout=8.0,
                        )
                except asyncio.TimeoutError:
                    logger.warning("URL validation timed out (8.0s) for %s", url)
                    return None
                except Exception as e:
                    logger.debug("URL validation exception for %s: %s", url, e)
                    return None

        tasks = [validate_with_sem(u, t) for u, t in candidate_urls[:12]]
        validated_raw = await asyncio.gather(*tasks, return_exceptions=True)

        verified_jobs: list[dict] = []
        seen_signatures: set[tuple[str, str]] = set()

        rejected_by_duplicate = 0
        for res in validated_raw:
            if isinstance(res, dict) and res:
                norm_comp = re.sub(r"[^\w]", "", res["company"].lower())
                norm_title = re.sub(r"[^\w]", "", res["title"].lower())
                sig = (norm_comp, norm_title)
                if sig not in seen_signatures:
                    seen_signatures.add(sig)
                    verified_jobs.append(res)
                else:
                    rejected_by_duplicate += 1

        val_elapsed = time.monotonic() - val_start
        logger.info(
            "URL VALIDATION END: %.2fs (extracted %d verified relevant jobs from %d candidates, duplicates: %d)",
            val_elapsed,
            len(verified_jobs),
            len(candidate_urls),
            rejected_by_duplicate,
        )

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
    start_time = time.monotonic()
    logger.info("SEARCH_JOBS START: role='%s', experience=%d, locations=%s, max_results=%d", role, experience_years, locations, max_results)

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
        elapsed = time.monotonic() - start_time
        logger.info("SEARCH_JOBS END: %.2fs (status=TEST_MOCK_DATA, jobs=%d)", elapsed, len(mock_subset[:max_results]))
        return json.dumps({
            "jobs": mock_subset[:max_results],
            "total_found": len(mock_subset[:max_results]),
            "status": "TEST_MOCK_DATA",
        })

    # Live Production Job Discovery
    if not settings.tavily_api_key:
        logger.warning("Tavily API key is not configured — live job search is unavailable.")
        elapsed = time.monotonic() - start_time
        logger.info("SEARCH_JOBS END: %.2fs (status=LIVE_JOB_SEARCH_UNAVAILABLE)", elapsed)
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

    elapsed = time.monotonic() - start_time
    status = "SUCCESS" if jobs else "NO_MATCHING_JOBS_FOUND"
    logger.info("SEARCH_JOBS END: %.2fs (status=%s, jobs=%d)", elapsed, status, len(jobs))

    return json.dumps({
        "jobs": jobs,
        "total_found": len(jobs),
        "status": status,
    })

