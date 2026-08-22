"""Application Agent — applies to matched jobs using original resume via MCP."""

from datetime import datetime, timezone
import logging

from langsmith import traceable
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.config import get_settings
from app.db.repository import Repository
from app.schemas import ApplicationResult, ManualActionItem, MatchedJob, UserProfile
from app.services.guardrails import Guardrails
from app.services.mcp_client import get_mcp_client
from app.services.resume_storage import verify_resume_integrity

logger = logging.getLogger(__name__)
settings = get_settings()


@traceable(name="application_agent")
async def application_agent(state: AgentState, session: AsyncSession) -> dict:
    profile = UserProfile(**state["user_profile"])
    mcp = get_mcp_client()
    guardrails = Guardrails(session)
    repo = Repository(session)

    resume_path = state["resume_file_path"]
    resume_record = await repo.get_resume(state["resume_id"])

    expected_hash = resume_record.file_hash if resume_record else ""

    applied: list[dict] = []
    pending: list[dict] = []
    failed: list[dict] = []

    attempted = state.get("applications_attempted", 0)
    max_apps = state.get(
        "max_applications_per_run",
        settings.max_applications_per_run,
    )

    seen_urls: set[str] = set()

    logger.info("-" * 60)
    logger.info(
        "APPLICATION AGENT START | matched_jobs=%d | max_applications=%d | threshold=%d",
        len(state.get("matched_jobs", [])),
        max_apps,
        settings.match_threshold,
    )
    logger.info("-" * 60)

    for idx, job_data in enumerate(state.get("matched_jobs", []), 1):
        job = MatchedJob(**job_data)

        logger.info(
            "APPLICATION CANDIDATE %d | company='%s' | title='%s' | score=%d",
            idx,
            job.company,
            job.title,
            job.match_score,
        )

        # ---------------------------------------------------------
        # FINAL APPLICATION SAFETY GATE
        # Never allow a job below the configured match threshold
        # to reach the actual application process.
        # ---------------------------------------------------------
        if job.match_score < settings.match_threshold:
            logger.warning(
                "APPLICATION GATE BLOCKED | company='%s' | title='%s' | "
                "score=%d | threshold=%d",
                job.company,
                job.title,
                job.match_score,
                settings.match_threshold,
            )
            continue

        # Skip duplicate URLs in same batch
        if job.application_url in seen_urls:
            logger.info(
                "DUPLICATE JOB SKIPPED | company='%s' | url='%s'",
                job.company,
                job.application_url,
            )
            continue

        seen_urls.add(job.application_url)

        # Check application limit guardrail
        if attempted >= max_apps:
            logger.info(
                "Reached maximum applications for this run (%d). "
                "Queuing remaining eligible jobs.",
                max_apps,
            )

            logger.info(
                "QUEUED FOR FUTURE RUN: %s / %s (score=%d)",
                job.company,
                job.title,
                job.match_score,
            )

            db_job = await repo.upsert_job(job)

            await repo.create_application(
                user_id=state["user_id"],
                job_id=db_job.job_id,
                resume_id=state["resume_id"],
                status="ELIGIBLE",
                match_score=job.match_score,
                run_id=state["run_id"],
            )

            continue

        logger.info(
            "APPLICATION PROCESSING START: %s / %s",
            job.company,
            job.title,
        )

        # ---------------------------------------------------------
        # Resume integrity verification
        # ---------------------------------------------------------
        if expected_hash:
            integrity = verify_resume_integrity(
                resume_path,
                expected_hash,
            )

            if not integrity["valid"]:
                logger.error(
                    "Resume integrity check FAILED for %s (%s): %s",
                    job.company,
                    job.title,
                    integrity["reason"],
                )

                failed.append(
                    ApplicationResult(
                        job_id=job.job_id,
                        company=job.company,
                        job_url=job.application_url,
                        status="FAILED",
                        resume_used=resume_path,
                        error=(
                            "Original resume integrity check failed: "
                            f"{integrity['reason']}"
                        ),
                    ).model_dump()
                )

                return {
                    "applied_jobs": applied,
                    "pending_manual_jobs": pending,
                    "failed_jobs": failed,
                    "applications_attempted": attempted,
                    "errors": [integrity["reason"]],
                    "application_complete": True,
                    "next_agent": "notification",
                }

            logger.info(
                "RESUME HASH VERIFIED: %s",
                expected_hash[:16],
            )

        # ---------------------------------------------------------
        # Upsert job
        # ---------------------------------------------------------
        db_job = await repo.upsert_job(job)
        job.job_id = db_job.job_id

        # ---------------------------------------------------------
        # Guardrails
        # ---------------------------------------------------------
        can_apply, reason = await guardrails.can_apply(
            state["user_id"],
            job,
        )

        if not can_apply:
            logger.info(
                "Guardrail blocked application to %s: %s",
                job.company,
                reason,
            )

            manual = ManualActionItem(
                company=job.company,
                job_url=job.application_url,
                reason=reason,
            )

            app = await repo.create_application(
                user_id=state["user_id"],
                job_id=job.job_id,
                resume_id=state["resume_id"],
                status="PENDING_MANUAL",
                match_score=job.match_score,
                run_id=state["run_id"],
            )

            await repo.create_manual_action(
                state["user_id"],
                manual,
                app.application_id,
            )

            pending.append(manual.model_dump())
            continue

        # ---------------------------------------------------------
        # MCP application
        # ---------------------------------------------------------
        logger.info(
            "MCP APPLY_JOB START: %s / %s",
            job.company,
            job.title,
        )

        logger.info(
            "BROWSER APPLICATION START: %s",
            job.application_url,
        )

        logger.info(
            "FORM FILL START: %s",
            job.company,
        )

        logger.info(
            "SUBMISSION ATTEMPT: %s",
            job.company,
        )

        try:
            result = await mcp.call_tool(
                "apply_job",
                {
                    "application_url": job.application_url,
                    "resume_file_path": resume_path,
                    "user_profile": profile.model_dump(),
                    "company": job.company,
                    "job_title": job.title,
                    "expected_resume_hash": expected_hash,
                    "mock_mode": settings.is_demo_mode,
                },
            )

        except Exception as exc:
            logger.error(
                "MCP apply_job tool error for %s: %s",
                job.company,
                exc,
            )

            result = {
                "status": "FAILED",
                "company": job.company,
                "job_title": job.title,
                "application_url": job.application_url,
                "reason": f"Tool execution error: {exc}",
                "confirmation": "",
                "submitted_at": None,
                "resume_hash": expected_hash,
            }

        attempted += 1

        status = result.get("status", "FAILED")

        logger.info(
            "SUBMISSION VERIFICATION: %s -> %s",
            job.company,
            status,
        )

        logger.info(
            "FINAL STATUS: %s for %s (%s)",
            status,
            job.company,
            job.title,
        )

        # ---------------------------------------------------------
        # MCP unavailable
        # ---------------------------------------------------------
        if status == "MCP_UNAVAILABLE":
            logger.error(
                "MCP server unavailable — cannot apply to %s",
                job.company,
            )

            failed.append(
                ApplicationResult(
                    job_id=job.job_id,
                    company=job.company,
                    job_url=job.application_url,
                    status="FAILED",
                    resume_used=resume_path,
                    error=(
                        "MCP server unavailable — cannot process "
                        "application"
                    ),
                ).model_dump()
            )

            continue

        # ---------------------------------------------------------
        # Successful verified submission
        # ---------------------------------------------------------
        if status == "SUCCESS":
            await guardrails.record_application_attempt(
                state["user_id"],
            )

            await repo.create_application(
                user_id=state["user_id"],
                job_id=job.job_id,
                resume_id=state["resume_id"],
                status="SUCCESS",
                match_score=job.match_score,
                run_id=state["run_id"],
            )

            applied.append(
                ApplicationResult(
                    job_id=job.job_id,
                    company=job.company,
                    job_url=job.application_url,
                    status="SUCCESS",
                    resume_used=resume_path,
                    applied_at=(
                        result.get("submitted_at")
                        or datetime.now(timezone.utc).isoformat()
                    ),
                    error=result.get("confirmation"),
                ).model_dump()
            )

        # ---------------------------------------------------------
        # Human-in-the-loop required
        # ---------------------------------------------------------
        elif status == "MANUAL_ACTION_REQUIRED":
            manual = ManualActionItem(
                company=job.company,
                job_url=job.application_url,
                reason=result.get(
                    "reason",
                    "Manual action required",
                ),
            )

            app = await repo.create_application(
                user_id=state["user_id"],
                job_id=job.job_id,
                resume_id=state["resume_id"],
                status="PENDING_MANUAL",
                match_score=job.match_score,
                run_id=state["run_id"],
            )

            await repo.create_manual_action(
                state["user_id"],
                manual,
                app.application_id,
            )

            pending.append(
                manual.model_dump()
            )

        # ---------------------------------------------------------
        # Failed application
        # ---------------------------------------------------------
        else:
            await repo.create_application(
                user_id=state["user_id"],
                job_id=job.job_id,
                resume_id=state["resume_id"],
                status="FAILED",
                match_score=job.match_score,
                run_id=state["run_id"],
            )

            failed.append(
                ApplicationResult(
                    job_id=job.job_id,
                    company=job.company,
                    job_url=job.application_url,
                    status="FAILED",
                    resume_used=resume_path,
                    error=result.get(
                        "reason",
                        "Application submission could not be verified",
                    ),
                ).model_dump()
            )

    await repo.commit()

    # -------------------------------------------------------------
    # Final application result
    # -------------------------------------------------------------
    logger.info("-" * 60)

    logger.info(
        "APPLICATION RESULT | success=%d | manual=%d | failed=%d | attempted=%d",
        len(applied),
        len(pending),
        len(failed),
        attempted,
    )

    logger.info("-" * 60)

    return {
        "applied_jobs": applied,
        "pending_manual_jobs": pending,
        "failed_jobs": failed,
        "applications_attempted": attempted,
        "application_complete": True,
        "next_agent": "notification",
    }