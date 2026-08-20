"""Job Search Agent — finds real individual openings via MCP search_jobs."""

import logging
from langsmith import traceable

from app.agents.state import AgentState
from app.config import get_settings
from app.services.mcp_client import get_mcp_client
from app.schemas import JobListing, UserProfile

logger = logging.getLogger(__name__)
settings = get_settings()


@traceable(name="job_search_agent")
async def job_search_agent(state: AgentState) -> dict:
    profile = UserProfile(**state["user_profile"])
    mcp = get_mcp_client()

    result = await mcp.call_tool(
        "search_jobs",
        {
            "role": profile.role,
            "skills": profile.skills,
            "locations": profile.locations,
            "experience_years": profile.experience,
            "max_results": 30,
            "test_mode": settings.test_mode or settings.is_demo_mode,
        },
    )

    raw_jobs = result.get("jobs") or result.get("partial_jobs") or []
    jobs = [JobListing(**j).model_dump() for j in raw_jobs]
    status = result.get("status", "")
    message = result.get("message") or result.get("error") or ""

    # Clear live logging for data-flow tracing (no secrets/PII)
    logger.info("SEARCH RESULTS: %d jobs", len(jobs))
    for idx, j in enumerate(jobs[:3], 1):
        logger.info("  Job %d: '%s' at '%s' (%s)", idx, j.get("title"), j.get("company"), j.get("application_url"))

    errors: list[str] = []
    if not jobs:
        if status == "LIVE_JOB_SEARCH_UNAVAILABLE":
            errors.append("Live job search is unavailable: Tavily API key is not configured in .env.")
        elif status == "SEARCH_TIMEOUT":
            errors.append(f"Job search timed out: {message or 'operation exceeded configured timeout'}.")
        elif status in ("FAILED", "TAVILY_SEARCH_FAILED"):
            errors.append(f"Job search failed: {message or status}.")
        else:
            errors.append(f"No matching individual job postings found for '{profile.role}'.")

    return {
        "jobs_found": jobs,
        "next_agent": "resume_match" if jobs else "notification",
        "errors": errors,
    }
