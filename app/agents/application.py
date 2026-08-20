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

    # CRITICAL: Verify original resume integrity
    if resume_record and not verify_resume_integrity(resume_path, resume_record.file_hash):
        return {
            "errors": ["Resume integrity verification failed — original file was modified"],
            "application_complete": True,
            "next_agent": "notification",
        }

    applied: list[dict] = []
    pending: list[dict] = []
    failed: list[dict] = []
    attempted = state.get("applications_attempted", 0)
    max_apps = state.get("max_applications_per_run", settings.max_applications_per_day)

    seen_urls: set[str] = set()

    for job_data in state.get("matched_jobs", []):
        if attempted >= max_apps:
            logger.info("Reached maximum applications for this run (%d)", max_apps)
            break

        job = MatchedJob(**job_data)

        # Skip duplicate URLs in same batch
        if job.application_url in seen_urls:
            continue
        seen_urls.add(job.application_url)

        # Upsert job in DB
        db_job = await repo.upsert_job(job)
        job.job_id = db_job.job_id

        # Check guardrails
        can_apply, reason = await guardrails.can_apply(state["user_id"], job)
        if not can_apply:
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
            await repo.create_manual_action(state["user_id"], manual, app.application_id)
            pending.append(manual.model_dump())
            continue

        # Invoke MCP apply_job tool
        try:
            result = await mcp.call_tool(
                "apply_job",
                {
                    "application_url": job.application_url,
                    "resume_file_path": resume_path,
                    "user_profile": profile.model_dump(),
                    "company": job.company,
                    "job_title": job.title,
                    "mock_mode": settings.is_demo_mode,
                },
            )
        except Exception as exc:
            logger.error("MCP apply_job tool error for %s: %s", job.company, exc)
            result = {
                "status": "FAILED",
                "company": job.company,
                "job_title": job.title,
                "application_url": job.application_url,
                "reason": f"Tool execution error: {exc}",
                "confirmation": "",
                "submitted_at": None,
                "resume_hash": resume_record.file_hash if resume_record else "",
            }

        attempted += 1
        status = result.get("status", "FAILED")

        if status == "SUCCESS":
            await guardrails.record_application_attempt(state["user_id"])
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
                    applied_at=result.get("submitted_at") or datetime.now(timezone.utc).isoformat(),
                    error=result.get("confirmation"),
                ).model_dump()
            )
        elif status == "MANUAL_ACTION_REQUIRED":
            manual = ManualActionItem(
                company=job.company,
                job_url=job.application_url,
                reason=result.get("reason", "Manual action required"),
            )
            app = await repo.create_application(
                user_id=state["user_id"],
                job_id=job.job_id,
                resume_id=state["resume_id"],
                status="PENDING_MANUAL",
                match_score=job.match_score,
                run_id=state["run_id"],
            )
            await repo.create_manual_action(state["user_id"], manual, app.application_id)
            pending.append(manual.model_dump())
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
                    error=result.get("reason", "Application submission could not be verified"),
                ).model_dump()
            )

    await repo.commit()

    return {
        "applied_jobs": applied,
        "pending_manual_jobs": pending,
        "failed_jobs": failed,
        "applications_attempted": attempted,
        "application_complete": True,
        "next_agent": "notification",
    }
