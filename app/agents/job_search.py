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
    logger.info(
        "JOB SEARCH START | role='%s' | experience=%s | locations=%s",
        profile.role,
        profile.experience,
        profile.locations,
    )

    mcp = get_mcp_client()

    # Build targeted search roles to improve job-discovery recall.
    search_roles = [
        profile.role,
        "AI Engineer",
        "Machine Learning Engineer",
        "Generative AI Engineer",
        "GenAI Engineer",
        "Python AI Engineer",
        "Junior AI Engineer",
        "LLM Engineer",
    ]

    # Remove duplicate search roles while preserving order.
    search_roles = list(
        dict.fromkeys(
            role.strip()
            for role in search_roles
            if role and role.strip()
        )
    )

    all_jobs = []
    seen_urls = set()

    last_status = ""
    last_message = ""

    for search_role in search_roles:
        logger.info(
            "JOB DISCOVERY QUERY | role='%s' | locations=%s",
            search_role,
            profile.locations,
        )

        try:
            result = await mcp.call_tool(
                "search_jobs",
                {
                    "role": search_role,
                    "skills": profile.skills,
                    "locations": profile.locations,
                    "experience_years": profile.experience,
                    "max_results": 10,
                    "test_mode": (
                        settings.test_mode
                        or settings.is_demo_mode
                    ),
                },
            )

            # Preserve the most recent search status/message
            # for final error reporting.
            last_status = result.get("status", "")
            last_message = (
                result.get("message")
                or result.get("error")
                or ""
            )

            mcp_jobs = result.get("jobs") or []
            mcp_partial = result.get("partial_jobs") or []

            candidates = mcp_jobs or mcp_partial or []

            logger.info(
                "JOB DISCOVERY QUERY RESULT | role='%s' | "
                "status=%s | candidates=%d",
                search_role,
                last_status or "UNKNOWN",
                len(candidates),
            )

            for job in candidates:
                url = (job.get("application_url") or "").strip()

                # Ignore jobs without an application URL.
                if not url:
                    continue

                # Remove duplicate job postings.
                if url in seen_urls:
                    continue

                seen_urls.add(url)
                all_jobs.append(job)

                # Respect the overall maximum.
                if len(all_jobs) >= 30:
                    break

            if len(all_jobs) >= 30:
                logger.info(
                    "JOB DISCOVERY LIMIT REACHED | unique_jobs=%d",
                    len(all_jobs),
                )
                break

        except Exception as exc:
            # One failed query should not stop the remaining searches.
            logger.warning(
                "JOB DISCOVERY QUERY FAILED | role='%s' | error='%s'",
                search_role,
                exc,
            )
            continue

    # Convert raw MCP results into validated JobListing objects.
    jobs = [
        JobListing(**job).model_dump()
        for job in all_jobs[:30]
    ]

    status = last_status
    message = last_message

    # --- DIAGNOSTIC: JOB DISCOVERY SUMMARY ---
    logger.info(
        "JOB DISCOVERY SUMMARY | unique_jobs=%d | queries=%d",
        len(jobs),
        len(search_roles),
    )

    logger.info("SEARCH RESULTS: %d jobs", len(jobs))

    for idx, job in enumerate(jobs[:3], 1):
        logger.info(
            "  Job %d: '%s' at '%s' (%s)",
            idx,
            job.get("title"),
            job.get("company"),
            job.get("application_url"),
        )

    errors: list[str] = []

    if not jobs:
        if status == "LIVE_JOB_SEARCH_UNAVAILABLE":
            errors.append(
                "Live job search is unavailable: "
                "Tavily API key is not configured in .env."
            )

        elif status == "SEARCH_TIMEOUT":
            errors.append(
                f"Job search timed out: "
                f"{message or 'operation exceeded configured timeout'}."
            )

        elif status in ("FAILED", "TAVILY_SEARCH_FAILED"):
            errors.append(
                f"Job search failed: {message or status}."
            )

        else:
            errors.append(
                f"No matching individual job postings found "
                f"for '{profile.role}'."
            )

    next_agent = "resume_match" if jobs else "notification"

    # --- DIAGNOSTIC: JOB SEARCH END ---
    logger.info(
        "JOB SEARCH END | jobs_found=%d | next_agent='%s' | errors=%s",
        len(jobs),
        next_agent,
        errors or "none",
    )
    logger.info("-" * 60)

    return {
        "jobs_found": jobs,
        "next_agent": next_agent,
        "errors": errors,
    }