"""Resume Match Agent — RAG + LLM structured scoring."""

from langsmith import traceable

from app.agents.state import AgentState
from app.config import get_settings
from app.rag.matcher import match_job_to_resume
from app.schemas import JobListing, MatchedJob, UserProfile

settings = get_settings()


@traceable(name="resume_match_agent")
async def resume_match_agent(state: AgentState) -> dict:
    profile = UserProfile(**state["user_profile"])
    threshold = state.get("match_threshold", settings.match_threshold)
    resume_id = state["resume_id"]

    matched: list[dict] = []
    errors: list[str] = []

    for job_data in state.get("jobs_found", []):
        job = JobListing(**job_data)
        try:
            result = match_job_to_resume(job, resume_id, profile)
            if "MATCHING_FAILED" in result.match_rationale:
                errors.append(f"{job.company} ({job.title}): {result.match_rationale}")
            elif result.match_score >= threshold:
                matched.append(result.model_dump())
        except Exception as exc:
            errors.append(f"Match failed for {job.company}: {exc}")

    return {
        "matched_jobs": matched,
        "next_agent": "application" if matched else "notification",
        "errors": errors,
    }
