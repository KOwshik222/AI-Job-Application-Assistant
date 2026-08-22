"""Resume Match Agent — RAG + LLM structured scoring and persistence."""

import logging
from langsmith import traceable
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.config import get_settings
from app.db.repository import Repository
from app.rag.matcher import is_quota_exhausted, match_job_to_resume, reset_quota_flag
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

    # [3] RAG Resume Chunks
    chunk_count = get_resume_chunks_count(resume_id)

    # Reset quota flag at the start of each matching run so stale flags
    # from a previous workflow don't block a new one.
    reset_quota_flag()

    # --- DIAGNOSTIC: RESUME MATCH START ---
    logger.info("-" * 60)
    logger.info("RESUME MATCH START | jobs_found=%d | resume_chunks=%d | threshold=%d",
                len(jobs_found), chunk_count, threshold)
    logger.info("-" * 60)

    matched: list[dict] = []
    not_matched: list[dict] = []
    errors: list[str] = []
    quota_skipped: int = 0

    repo = Repository(session) if session else None

    for job_data in jobs_found:
        job = JobListing(**job_data)

        # If Gemini quota was already exhausted, skip remaining jobs
        # instead of making doomed API calls.
        if is_quota_exhausted():
            quota_skipped += 1
            logger.info("  MATCH SKIPPED (quota) | company='%s' | title='%s'",
                        job.company, job.title)
            continue

        logger.info("  MATCH EVAL | company='%s' | title='%s'", job.company, job.title)
        try:
            result = match_job_to_resume(job, resume_id, profile)

            if "LLM_QUOTA_EXCEEDED" in result.match_rationale:
                logger.warning("  MATCH RESULT | company='%s' | title='%s' | result=QUOTA_EXCEEDED",
                               job.company, job.title)
                errors.append(f"{job.company} ({job.title}): {result.match_rationale}")
                # Don't count as matched or not_matched — these are unprocessed
                continue
            elif "MATCHING_FAILED" in result.match_rationale:
                logger.info("  MATCH RESULT | company='%s' | title='%s' | score=%d | threshold=%d | result=ERROR",
                            job.company, job.title, result.match_score, threshold)
                errors.append(f"{job.company} ({job.title}): {result.match_rationale}")
            elif result.match_score >= threshold:
                logger.info("  MATCH RESULT | company='%s' | title='%s' | score=%d | threshold=%d | result=PASS",
                            job.company, job.title, result.match_score, threshold)
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
                logger.info("  MATCH RESULT | company='%s' | title='%s' | score=%d | threshold=%d | result=REJECT",
                            job.company, job.title, result.match_score, threshold)
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

    # --- DIAGNOSTIC: MATCH SUMMARY ---
    logger.info("-" * 60)
    logger.info("MATCH SUMMARY | eligible=%d | rejected=%d | errors=%d | quota_skipped=%d | threshold=%d",
                len(matched), len(not_matched), len(errors), quota_skipped, threshold)
    if quota_skipped > 0:
        logger.warning("MATCH SUMMARY | %d jobs could not be evaluated due to LLM quota exhaustion", quota_skipped)
    logger.info("-" * 60)

    # Add a summary error if quota was exhausted
    if quota_skipped > 0 or is_quota_exhausted():
        errors.append(
            f"LLM_QUOTA_EXCEEDED: Gemini API quota exhausted. "
            f"{quota_skipped} job(s) could not be evaluated. "
            f"Resume matching when quota is available."
        )

    return {
        "matched_jobs": matched,
        "next_agent": "application" if matched else "notification",
        "errors": errors,
    }

