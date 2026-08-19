"""Application Agent — applies using original resume via MCP."""

from datetime import datetime, timezone

from langsmith import traceable
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.config import get_settings
from app.db.repository import Repository
from app.schemas import ApplicationResult, ManualActionItem, MatchedJob, UserProfile
from app.services.guardrails import Guardrails
from app.services.mcp_client import get_mcp_client
from app.services.resume_storage import verify_resume_integrity

settings = get_settings()


@traceable(name="application_agent")
async def application_agent(state: AgentState, session: AsyncSession) -> dict:
    profile = UserProfile(**state["user_profile"])
    mcp = get_mcp_client()
    guardrails = Guardrails(session)
    repo = Repository(session)

    resume_path = state["resume_file_path"]
    resume_record = await repo.get_resume(state["resume_id"])
    if resume_record and not verify_resume_integrity(resume_path, resume_record.file_hash):
        return {
            "errors": ["Resume integrity check failed — file may have been modified"],
            "application_complete": True,
            "next_agent": "notification",
        }

    applied: list[dict] = []
    pending: list[dict] = []
    failed: list[dict] = []
    attempted = state.get("applications_attempted", 0)
    max_apps = state.get("max_applications_per_run", min(5, settings.max_applications_per_day))

    seen_urls: set[str] = set()
    for job_data in state.get("matched_jobs", []):
        if attempted >= max_apps:
            break

        job = MatchedJob(**job_data)
        if job.application_url in seen_urls:
            continue
        seen_urls.add(job.application_url)

        db_job = await repo.upsert_job(job)
        job.job_id = db_job.job_id

        can_apply, reason = await guardrails.can_apply(state["user_id"], job)
        if not can_apply:
            manual = ManualActionItem(
                company=job.company,
                job_url=job.application_url,
                reason=reason,
            )
            app = await repo.create_application(
                state["user_id"],
                job.job_id,
                state["resume_id"],
                "PENDING_MANUAL",
                job.match_score,
                state["run_id"],
            )
            await repo.create_manual_action(state["user_id"], manual, app.application_id)
            pending.append(manual.model_dump())
            continue

        try:
            result = await mcp.call_tool(
                "apply_job",
                {
                    "application_url": job.application_url,
                    "resume_file_path": resume_path,
                    "user_profile": profile.model_dump(),
                    "company": job.company,
                    "job_title": job.title,
                    "mock_mode": False,
                },
            )
        except Exception as exc:
            result = {
                "status": "FAILED",
                "reason": f"Browser tool error: {exc}",
                "resume_used": resume_path,
            }

        attempted += 1
        status = result.get("status", "FAILED")

        if status == "SUCCESS":
            await guardrails.record_application_attempt(state["user_id"])
            await repo.create_application(
                state["user_id"],
                job.job_id,
                state["resume_id"],
                "SUCCESS",
                job.match_score,
                state["run_id"],
            )
            applied.append(
                ApplicationResult(
                    job_id=job.job_id,
                    company=job.company,
                    job_url=job.application_url,
                    status="SUCCESS",
                    resume_used=resume_path,
                    applied_at=datetime.now(timezone.utc).isoformat(),
                ).model_dump()
            )
        elif status == "MANUAL_ACTION_REQUIRED":
            manual = ManualActionItem(
                company=job.company,
                job_url=job.application_url,
                reason=result.get("reason", "Manual action required"),
            )
            app = await repo.create_application(
                state["user_id"],
                job.job_id,
                state["resume_id"],
                "PENDING_MANUAL",
                job.match_score,
                state["run_id"],
            )
            await repo.create_manual_action(state["user_id"], manual, app.application_id)
            pending.append(manual.model_dump())
        else:
            await repo.create_application(
                state["user_id"],
                job.job_id,
                state["resume_id"],
                "FAILED",
                job.match_score,
                state["run_id"],
            )
            failed.append(
                ApplicationResult(
                    job_id=job.job_id,
                    company=job.company,
                    job_url=job.application_url,
                    status="FAILED",
                    resume_used=resume_path,
                    error=result.get("reason", "Application failed"),
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
