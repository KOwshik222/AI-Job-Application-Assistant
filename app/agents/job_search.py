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

    # --- DIAGNOSTIC: JOB SEARCH START ---
    logger.info("-" * 60)
    logger.info("JOB SEARCH START | role='%s' | experience=%s | locations=%s",
                profile.role, profile.experience, profile.locations)

    mcp = get_mcp_client()

    # --- DIAGNOSTIC: MCP search_jobs START ---
    logger.info("MCP search_jobs START | test_mode=%s", settings.test_mode or settings.is_demo_mode)

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

    # --- DIAGNOSTIC: MCP search_jobs RESULT ---
    mcp_status = result.get("status", "UNKNOWN")
    mcp_jobs = result.get("jobs") or []
    mcp_partial = result.get("partial_jobs") or []
    mcp_error = result.get("error") or result.get("message") or ""
    logger.info("MCP search_jobs RESULT | status=%s | jobs=%d | partial_jobs=%d | error/message='%s'",
                mcp_status, len(mcp_jobs), len(mcp_partial), mcp_error)

    raw_jobs = mcp_jobs or mcp_partial or []
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

    next_agent = "resume_match" if jobs else "notification"

    # --- DIAGNOSTIC: JOB SEARCH END ---
    logger.info("JOB SEARCH END | jobs_found=%d | next_agent='%s' | errors=%s",
                len(jobs), next_agent, errors or "none")
    logger.info("-" * 60)

    return {
        "jobs_found": jobs,
        "next_agent": next_agent,
        "errors": errors,
    }

