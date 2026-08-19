"""Job Search Agent — finds openings via MCP search_jobs."""

from langsmith import traceable

from app.agents.state import AgentState
from app.services.mcp_client import get_mcp_client
from app.schemas import JobListing, UserProfile


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
        },
    )

    jobs = [JobListing(**j).model_dump() for j in result.get("jobs", [])]
    return {
        "jobs_found": jobs,
        "next_agent": "resume_match",
        "errors": [] if jobs else ["No jobs found"],
    }
