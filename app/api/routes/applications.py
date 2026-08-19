"""Applications and summary endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import get_settings
from app.db.repository import Repository
from app.schemas import (
    ApplicationResponse,
    ApplicationSummaryResponse,
    ApplicationsListResponse,
    ManualActionItem,
    ManualActionResponse,
    ManualActionsListResponse,
)
from app.services.workflow_runner import get_latest_run_for_user, get_run_status

router = APIRouter(prefix="/api/v1", tags=["applications"])
settings = get_settings()


@router.get("/applications", response_model=ApplicationsListResponse)
async def list_applications(
    user_id: str = Query(...),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    repo = Repository(session)
    rows, total = await repo.list_applications(user_id, status, limit, offset)
    apps = [
        ApplicationResponse(
            application_id=app.application_id,
            company=job.company,
            job_title=job.title,
            status=app.status,
            match_score=app.match_score,
            applied_at=app.applied_at,
            job_url=job.url,
        )
        for app, job in rows
    ]
    return ApplicationsListResponse(applications=apps, total=total)


@router.get("/manual-actions", response_model=ManualActionsListResponse)
async def list_manual_actions(
    user_id: str = Query(...),
    status: str | None = Query("PENDING_MANUAL_ACTION"),
    session: AsyncSession = Depends(get_db),
):
    repo = Repository(session)
    actions = await repo.list_manual_actions(user_id, status)
    return ManualActionsListResponse(
        manual_actions=[
            ManualActionResponse(
                action_id=a.action_id,
                company=a.company,
                url=a.url,
                reason=a.reason,
                status=a.status,
            )
            for a in actions
        ]
    )


@router.get("/application-summary", response_model=ApplicationSummaryResponse)
async def application_summary(
    run_id: str | None = Query(None),
    user_id: str | None = Query(None),
):
    data = None
    if run_id:
        data = get_run_status(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="Run not found")
        rid = run_id
    elif user_id:
        latest = get_latest_run_for_user(user_id)
        if not latest:
            raise HTTPException(status_code=404, detail="No runs found for user")
        data = latest
        rid = latest["run_id"]
    else:
        raise HTTPException(status_code=400, detail="Provide run_id or user_id")

    state = data.get("state") or {}
    summary = state.get("email_summary") or {}
    log_path = settings.data_dir / "email_logs" / f"{rid}.html"

    return ApplicationSummaryResponse(
        run_id=rid,
        status=data.get("status", "UNKNOWN"),
        applied_successfully=summary.get("applied_successfully", len(state.get("applied_jobs", []))),
        manual_action_required=summary.get(
            "manual_action_required", len(state.get("pending_manual_jobs", []))
        ),
        failed=summary.get("failed", len(state.get("failed_jobs", []))),
        pending_manual_jobs=[
            ManualActionItem(**p) for p in state.get("pending_manual_jobs", [])
        ],
        email_sent=state.get("notification_sent", False),
        email_status=state.get("email_status", "UNKNOWN"),
        email_note=state.get("email_note", ""),
        email_log_url=f"/api/v1/email-log/{rid}" if log_path.exists() else None,
        jobs_found=len(state.get("jobs_found", [])),
        matched_jobs=len(state.get("matched_jobs", [])),
        errors=[
            e for e in (
                state.get("errors", []) if state else []
            )
            if e
        ] or ([data["error"]] if data.get("error") else []),
    )
