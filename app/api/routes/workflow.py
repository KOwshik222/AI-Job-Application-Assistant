"""Workflow trigger endpoint."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.repository import Repository
from app.schemas import StartJobSearchRequest, StartJobSearchResponse
from app.services.workflow_runner import run_workflow

router = APIRouter(prefix="/api/v1", tags=["workflow"])


@router.post("/start-job-search", response_model=StartJobSearchResponse)
async def start_job_search(
    request: StartJobSearchRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    repo = Repository(session)
    resume = await repo.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.user_id != request.user_id:
        raise HTTPException(status_code=403, detail="Resume does not belong to user")

    run_id = str(uuid.uuid4())
    background_tasks.add_task(run_workflow, request, resume.file_path, run_id)

    return StartJobSearchResponse(
        run_id=run_id,
        status="RUNNING",
        message="Workflow started. Poll GET /api/v1/application-summary?run_id=...",
    )


@router.post("/start-job-search/sync", response_model=StartJobSearchResponse)
async def start_job_search_sync(
    request: StartJobSearchRequest,
    session: AsyncSession = Depends(get_db),
):
    """Synchronous variant — waits for workflow completion (useful for testing)."""
    repo = Repository(session)
    resume = await repo.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.user_id != request.user_id:
        raise HTTPException(status_code=403, detail="Resume does not belong to user")

    run_id = await run_workflow(request, resume.file_path)
    return StartJobSearchResponse(
        run_id=run_id,
        status="COMPLETED",
        message=f"Workflow completed. Run ID: {run_id}",
    )
