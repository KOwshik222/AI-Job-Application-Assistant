"""Resume Match Agent — RAG + LLM structured scoring and persistence."""

import logging
from langsmith import traceable
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.config import get_settings
from app.db.repository import Repository
from app.rag.matcher import match_job_to_resume
from app.rag.vectorstore import get_resume_chunks_count
from app.schemas import JobListing, ManualActionItem, MatchedJob, UserProfile

logger = logging.getLogger(__name__)
settings = get_settings()


@traceable(name="resume_match_agent")
async def resume_match_agent(state: AgentState, session: AsyncSession | None = None) -> dict:
    profile = UserProfile(**state["user_profile"])
    threshold = state.get("match_threshold", settings.match_threshold)
    resume_id = state["resume_id"]

    jobs_found = state.get("jobs_found", [])
    logger.info("MATCH INPUT JOB COUNT: %d", len(jobs_found))

    # [3] RAG Resume Chunks
    chunk_count = get_resume_chunks_count(resume_id)
    logger.info("RESUME CHUNKS: %d", chunk_count)

    matched: list[dict] = []
    not_matched: list[dict] = []
    errors: list[str] = []

    repo = Repository(session) if session else None

    for job_data in jobs_found:
        job = JobListing(**job_data)
        logger.info("RAG MATCH START: %s / %s", job.company, job.title)
        try:
            result = match_job_to_resume(job, resume_id, profile)
            logger.info("RAG MATCH END: score=%d", result.match_score)
            logger.info("MATCH SCORE: %d", result.match_score)
            logger.info("MATCH THRESHOLD: %d", threshold)

            if "MATCHING_FAILED" in result.match_rationale:
                logger.info("MATCH RESULT: ERROR")
                errors.append(f"{job.company} ({job.title}): {result.match_rationale}")
            elif result.match_score >= threshold:
                logger.info("APPLICATION ELIGIBILITY: %s / %s (score=%d >= %d) -> ELIGIBLE_FOR_APPLICATION", job.company, job.title, result.match_score, threshold)
                logger.info("MATCH RESULT: PASS (ELIGIBLE)")
                matched.append(result.model_dump())

                if repo:
                    db_job = await repo.upsert_job(job)
                    await repo.create_application(
                        user_id=state["user_id"],
                        job_id=db_job.job_id,
                        resume_id=state["resume_id"],
                        status="ELIGIBLE",
                        match_score=result.match_score,
                        run_id=state["run_id"],
                    )
            else:
                logger.info("MATCH RESULT: REJECT (NOT_MATCHED, score=%d < %d)", result.match_score, threshold)
                not_matched.append(result.model_dump())

                if repo:
                    db_job = await repo.upsert_job(job)
                    await repo.create_application(
                        user_id=state["user_id"],
                        job_id=db_job.job_id,
                        resume_id=state["resume_id"],
                        status="NOT_MATCHED",
                        match_score=result.match_score,
                        run_id=state["run_id"],
                    )
        except Exception as exc:
            logger.error("Match failed for %s (%s): %s", job.company, job.title, exc)
            errors.append(f"Match failed for {job.company}: {exc}")

    if repo:
        await repo.commit()

    logger.info(
        "MATCH SUMMARY: %d eligible (>= %d), %d not matched (< %d)",
        len(matched),
        threshold,
        len(not_matched),
        threshold,
    )

    return {
        "matched_jobs": matched,
        "next_agent": "application" if matched else "notification",
        "errors": errors,
    }

